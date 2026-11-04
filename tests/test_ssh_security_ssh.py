"""Actual SSH with owned temporary agent/PTYS; never user agent or Keychain."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time

import pytest
import access_identity
import access_preview
import access_setup
import hosts
import ssh_discovery
from tests.test_access_identity_ssh import configured
from tests.test_access_setup_ssh import authorization
from tests.test_hosts_ssh import endpoints


@contextlib.contextmanager
def owned_agent(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='pimux-cache-test-',dir='/tmp') as directory:
        socket=Path(directory)/'socket'
        process=subprocess.Popen(['/usr/bin/ssh-agent','-D','-a',str(socket)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            deadline=time.monotonic()+3
            while not socket.exists():
                assert process.poll() is None and time.monotonic()<deadline
                time.sleep(.01)
            monkeypatch.setenv('SSH_AUTH_SOCK',str(socket))
            yield socket
        finally:
            process.terminate();process.wait(timeout=3)


def agent_keys():
    result=subprocess.run(['/usr/bin/ssh-add','-L'],capture_output=True,timeout=3)
    assert result.returncode in (0,1)
    return result.returncode,result.stdout


def test_authorization_and_inspection_do_not_add_file_keys_to_existing_agent(authorization,tmp_path,monkeypatch):
    host,public,_,_,_,_,_=authorization;profile,_=configured(host,tmp_path)
    child=tmp_path/'identity choices.conf'
    child.write_text(child.read_text().replace(' IdentityAgent none\n','')+' AddKeysToAgent yes\n')
    with owned_agent(monkeypatch):
        # This bootstrap identity is deliberately preloaded by the test only.
        subprocess.run(['/usr/bin/ssh-add',host['identity_file']],capture_output=True,check=True,timeout=3)
        before=agent_keys()
        result=asyncio.run(access_setup.enroll(profile,public,lambda _:True,tmp_path/'receipts'))
        assert result['status']=='installed_and_verified',result
        assert agent_keys()==before
        result=asyncio.run(hosts.fetch_host(profile))
        assert result['status']=='connected',result
        assert agent_keys()==before
        # Existing matching agent use remains possible, but a merely loaded
        # selected file must not have silently become another cached identity.
        Path(str(public)[:-4]).rename(tmp_path/'removed_selected_file')
        result=asyncio.run(hosts.fetch_host(profile))
        assert result['status']=='authentication_error' and agent_keys()==before,result


@pytest.mark.parametrize('authorization',['beta'],indirect=True)
def test_jump_and_target_file_keys_never_populate_the_temporary_agent(authorization,tmp_path,monkeypatch):
    host,public,name,_,_,docker,manifest=authorization
    gateway=manifest['containers']['alpha']
    address=docker('inspect','-f','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',name).strip()
    target_key=' '.join(docker('exec',name,'cat','/fixture/host_key.pub').split()[:2])
    known=tmp_path/'known hosts';known.write_text(Path(host['known_hosts']).read_text()+f'[{address}]:2222 {target_key}\n')
    config=tmp_path/'jump config'
    config.write_text(f'Host gateway\n HostName 127.0.0.1\n Port {manifest["hosts"][0]["port"]}\n'
                     f'Host selected\n HostName {address}\n Port 2222\n ProxyJump gateway\n'
                     f'Host *\n User fixture\n IdentityFile {json.dumps(host["identity_file"])}\n'
                     f' UserKnownHostsFile {json.dumps(str(known))}\n GlobalKnownHostsFile /dev/null\n IdentitiesOnly yes\n AddKeysToAgent yes\n')
    original=docker('exec',gateway,'cat','/etc/ssh/sshd_config')
    def change(value):
        docker('exec',gateway,'python3','-c','from pathlib import Path; import os,signal,sys; Path("/etc/ssh/sshd_config").write_text(sys.argv[1]); os.kill(int(Path("/run/sshd/fixture.pid").read_text()),signal.SIGHUP)',value)
    try:
        change(original.replace('AllowTcpForwarding no','AllowTcpForwarding local')+f'\nPermitOpen {address}:2222\n')
        with owned_agent(monkeypatch):
            before=agent_keys();assert before[0]==1
            selected=ssh_discovery.profile('selected',config)
            result=asyncio.run(access_setup.enroll(selected,public,lambda _:True,tmp_path/'receipts'))
            assert result['status']=='installed_and_verified' and agent_keys()==before,result
            assert asyncio.run(hosts.fetch_host(selected))['status']=='connected'
            assert agent_keys()==before
    finally: change(original)


PTY_DRIVER = '''import asyncio,json,os,signal,subprocess,sys,termios,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import hosts
mode,config,output=sys.argv[2:]
expected=termios.tcgetattr(0);real=hosts.exchange;spawn=subprocess.Popen;selector=hosts.selectors.DefaultSelector
children=[];rows=[]
def start(*args,**kwargs):
 process=spawn(*args,**kwargs)
 if not str(args[0][0]).endswith('/ssh'): return process
 children.append(process)
 Path(output+'.pids').write_text(json.dumps([child.pid for child in children]))
 deadline=time.monotonic()+3
 while termios.tcgetattr(0)[3]&termios.ECHO:
  if process.poll() is not None or time.monotonic()>deadline: raise RuntimeError('masked prompt never arrived')
  time.sleep(.005)
 return process
class FailedSelector(selector):
 def select(self,*args): raise RuntimeError('controlled exception while actual SSH awaits a passphrase')
async def exchange(argv,payload,timeout,env=None):
 previous=hosts.selectors.DefaultSelector
 try:
  if mode=='exception': hosts.selectors.DefaultSelector=FailedSelector
  return await real(argv,payload,.2 if mode=='timeout' else 5,env)
 finally: hosts.selectors.DefaultSelector=previous
hosts.subprocess.Popen=start;hosts.exchange=exchange
for _ in range(2):
 try: code=hosts.main(['--ssh-config',config,'inspect','selected','--json'])
 except SystemExit as error: code=error.code
 except RuntimeError: code='exception'
 rows.append(dict(code=code,restored=termios.tcgetattr(0)==expected,ssh_reaped=children[-1].poll() is not None,pid=children[-1].pid))
 Path(output).write_text(json.dumps(rows))
'''


@pytest.mark.parametrize('mode',['timeout','sigint','sigterm','exception'])
def test_real_ssh_prompt_interruptions_restore_full_terminal_and_reap_children(authorization,tmp_path,mode):
    host,public,_,_,_,_,_=authorization;profile,_=configured(host,tmp_path)
    assert asyncio.run(access_setup.enroll(profile,public,lambda _:True,tmp_path/'receipts'))['identity_saved']
    phrase='Ephemeral-fixture-phrase'
    subprocess.run(['/usr/bin/ssh-keygen','-p','-P','','-N',phrase,'-f',str(public)[:-4]],check=True,capture_output=True,timeout=5)
    master,slave=os.openpty();saved=termios.tcgetattr(slave);output=tmp_path/'result.json'
    sentinel=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
    process=subprocess.Popen([sys.executable,'-B','-c',PTY_DRIVER,str(Path(hosts.__file__).parent),mode,profile['ssh_config'],str(output)],
                             stdin=slave,stdout=slave,stderr=slave,start_new_session=True,env={**os.environ,'SSH_AUTH_SOCK':''})
    captured=bytearray();prompts=0;started=time.monotonic()
    try:
        deadline=started+10
        while process.poll() is None and time.monotonic()<deadline:
            if select.select([master],[],[],.05)[0]: captured.extend(os.read(master,65536))
            count=bytes(captured).lower().count(b'enter passphrase')
            if count>prompts:
                assert count==prompts+1 and count<=2
                prompts=count
                if mode in {'sigint','sigterm'}: os.kill(process.pid,signal.SIGINT if mode=='sigint' else signal.SIGTERM)
        assert process.poll()==0 and prompts==2,bytes(captured).decode(errors='replace')
        assert phrase.encode() not in captured
        rows=json.loads(output.read_text())
        assert len(rows)==2 and all(row['restored'] and row['ssh_reaped'] for row in rows),rows
        assert all(row['code']=={'timeout':1,'sigint':130,'sigterm':143,'exception':'exception'}[mode] for row in rows),rows
        assert termios.tcgetattr(slave)==saved and sentinel.poll() is None
        groups={row['pid'] for row in rows}
        states=subprocess.check_output(['/bin/ps','-axo','pid=,pgid=,stat='],text=True)
        assert not [line for line in states.splitlines() if int(line.split()[1]) in groups and not line.split()[2].startswith('Z')]
        assert time.monotonic()-started<10
    finally:
        if process.poll() is None: process.kill();process.wait(timeout=2)
        pids=Path(str(output)+'.pids')
        if pids.exists():
            for pid in json.loads(pids.read_text()):
                try: os.killpg(pid,signal.SIGKILL)
                except (ProcessLookupError,PermissionError): pass
        sentinel.terminate();sentinel.wait(timeout=2)
        termios.tcsetattr(slave,termios.TCSANOW,saved)
        os.close(master);os.close(slave)
