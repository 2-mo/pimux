"""Credential policy and real terminal cleanup, without user credentials/network."""
import asyncio
import contextlib
import io
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import termios
import threading
import time

import pytest
import access_identity
import access_transport
import hosts
import ssh_discovery
from tests.test_access_identity import selected, evaluated


@pytest.mark.parametrize('value',['yes','ask','confirm','10m'])
def test_all_hops_override_inherited_credential_caching(selected,value):
    host,key,_,child=selected
    child.write_text(child.read_text()+f' AddKeysToAgent {value}\n IgnoreUnknown UseKeychain\n UseKeychain yes\n')
    original=child.read_bytes()
    with access_transport.connection(host,key_only=access_identity.identity(key)) as (argv,env,root):
        target=evaluated([argv[0],'-G',*argv[1:]],env)
        assert target['addkeystoagent']==['false']
        projected=argv[argv.index('-F')+1]
        for depth in (1,2):
            hop=evaluated([argv[0],'-G','-F',projected,'gateway'],{**env,'PIMUX_SSH_DEPTH':str(depth)})
            assert hop['addkeystoagent']==['false']
            assert hop['identityfile']==['/fictional/first','/fictional/second']
            assert hop['stricthostkeychecking']==['true']
    assert child.read_bytes()==original


@pytest.mark.parametrize('platform',['darwin','linux'])
def test_native_and_wrapped_invocations_disable_only_supported_cache_options(selected,monkeypatch,platform):
    import ssh_hop
    host,_,_,_=selected
    monkeypatch.setattr(sys,'platform',platform)
    argv=hosts.ssh_command(host)
    assert 'AddKeysToAgent=no' in argv
    assert ('UseKeychain=no' in argv)==(platform=='darwin')
    with access_transport.connection(host) as (argv,env,root):
        for key in ('PIMUX_SSH_LOG_DIR','PIMUX_SSH_WRAPPER','PIMUX_SSH_DEPTH'):
            monkeypatch.setenv(key,env[key])
        monkeypatch.setenv('PIMUX_INTERACTIVE_AUTH','1')
        monkeypatch.setattr(sys,'argv',['ssh','-o','AddKeysToAgent=yes','-G','fictional'])
        monkeypatch.setattr(ssh_hop.resource,'setrlimit',lambda *_:None)
        captured=[]
        monkeypatch.setattr(os,'execv',lambda binary,args:captured.append((binary,args)))
        ssh_hop.main()
        args=captured[0][1]
        assert args.index('AddKeysToAgent=no')<args.index('AddKeysToAgent=yes')
        assert ('UseKeychain=no' in args)==(platform=='darwin')
        assert 'BatchMode=no' in args


@pytest.mark.parametrize('mode',['timeout','cancel','sigterm','exception'])
@pytest.mark.parametrize('echo',[True,False])
def test_inspect_restores_real_pty_after_prompt_failure_and_repeated_calls(tmp_path,monkeypatch,mode,echo):
    master,slave=os.openpty()
    original=termios.tcgetattr(slave)
    expected=termios.tcgetattr(slave)
    if echo: expected[3]|=termios.ECHO
    else: expected[3]&=~termios.ECHO
    termios.tcsetattr(slave,termios.TCSANOW,expected)
    tty=os.ttyname(slave);children=[];seen=[]
    host=ssh_discovery.profile('synthetic',tmp_path/'unused-config')
    helper=Path(hosts.__file__).with_name('ssh_askpass.py')
    real_exchange=hosts.exchange;real_popen=subprocess.Popen
    real_selector=hosts.selectors.DefaultSelector
    sentinel=real_popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
    @contextlib.contextmanager
    def connection(*args,**kwargs):
        yield [sys.executable,'-B',str(helper),'Enter passphrase for fictional key:'],{**os.environ,'PIMUX_AUTH_TTY':tty,'SSH_AUTH_SOCK':''},tmp_path
    def spawn(*args,**kwargs):
        process=real_popen(*args,**kwargs);children.append(process)
        prompt=bytearray();deadline=time.monotonic()+3
        while b'Enter passphrase' not in prompt:
            assert process.poll() is None and time.monotonic()<deadline
            if select.select([master],[],[],.05)[0]: prompt.extend(os.read(master,4096))
        assert not termios.tcgetattr(slave)[3]&termios.ECHO
        seen.append(True)
        return process
    class FailedSelector(real_selector):
        def select(self,*args): raise RuntimeError('controlled transport failure during masked prompt')
    async def exchange(argv,payload,timeout,env=None):
        if mode=='cancel': asyncio.get_running_loop().call_later(.05,asyncio.current_task().cancel)
        if mode=='sigterm': asyncio.get_running_loop().call_later(.05,os.kill,os.getpid(),signal.SIGTERM)
        # Affect the transport selector only, after asyncio has created its own.
        with monkeypatch.context() as scoped:
            if mode=='exception': scoped.setattr(hosts.selectors,'DefaultSelector',FailedSelector)
            return await real_exchange(argv,payload,.1 if mode=='timeout' else 2,env)
    stream=os.fdopen(os.dup(slave),'r')
    try:
        monkeypatch.setattr(sys,'stdin',stream)
        monkeypatch.setattr(hosts,'read_config',lambda *_:[host])
        monkeypatch.setattr(access_identity,'load',lambda *_:{'key':{'fingerprint':'SHA256:fictional'}})
        monkeypatch.setattr(access_identity,'identity',lambda _:Path('/fictional/key'))
        monkeypatch.setattr(access_transport,'connection',connection)
        monkeypatch.setattr(subprocess,'Popen',spawn)
        monkeypatch.setattr(hosts,'exchange',exchange)
        for _ in range(2):
            started=time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()):
                try: code=hosts.main(['--config',str(tmp_path/'unused-inventory'),'inspect',host['host_id']])
                except SystemExit as error: code=error.code
                except RuntimeError:
                    assert mode=='exception';code='exception'
            assert code=={'timeout':1,'cancel':130,'sigterm':143,'exception':'exception'}[mode]
            assert termios.tcgetattr(slave)==expected
            assert children[-1].poll() is not None and sentinel.poll() is None
            assert time.monotonic()-started<4
        assert len(children)==len(seen)==2
    finally:
        for process in children:
            if process.poll() is None: os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
        sentinel.terminate();sentinel.wait(timeout=2)
        termios.tcsetattr(slave,termios.TCSANOW,original)
        stream.close();os.close(master);os.close(slave)


def test_connection_restores_terminal_before_the_next_host_without_outer_cli(selected):
    host,_,_,_=selected;master,slave=os.openpty();expected=termios.tcgetattr(slave)
    tty=os.ttyname(slave);helper=Path(hosts.__file__).with_name('ssh_askpass.py')
    try:
        for _ in range(2):
            drained=[]
            def release_blocked_output():
                if select.select([master],[],[],0)[0]: drained.append(os.read(master,4096))
            # A buggy TCSAFLUSH restoration must fail this test, not hang the
            # entire runner waiting for the test to consume its unread prompt.
            watchdog=threading.Timer(3,release_blocked_output);watchdog.daemon=True;watchdog.start()
            try:
                with pytest.raises(TimeoutError):
                    with access_transport.connection(host,tty=tty) as (_,env,_):
                        asyncio.run(hosts.exchange([sys.executable,'-B',str(helper),'Enter passphrase for fictional key:'],b'',.5,env))
            finally: watchdog.cancel();watchdog.join(timeout=.5)
            assert not drained,'Terminal restoration waited for unread output to drain'
            assert termios.tcgetattr(slave)==expected
            assert select.select([master],[],[],0)[0]
            assert b'Enter passphrase' in os.read(master,4096)
    finally:
        termios.tcsetattr(slave,termios.TCSANOW,expected)
        os.close(master);os.close(slave)
