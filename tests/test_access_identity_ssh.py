"""Identity conflicts on real disposable SSH servers; never real user servers."""
import asyncio
import errno
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import time
import tempfile

import pytest
import access_identity
import access_preview
import access_setup
import access_transport
import hosts
import ssh_discovery
from tests.test_access_setup_ssh import authorization, reap_until_deadline
from tests.test_hosts_ssh import endpoints


def configured(host,tmp_path):
    config=tmp_path/'existing config';child=tmp_path/'identity choices.conf'
    child.write_text(f'Host *\n IdentityFile {json.dumps(host["identity_file"])}\n IdentityFile /fictional/another\n'
                     ' CertificateFile /fictional/certificate\n IdentitiesOnly yes\n IdentityAgent none\n')
    config.write_text(f'Include {json.dumps(str(child))}\nHost selected\n HostName 127.0.0.1\n Port {host["port"]}\n'
                     f' User fixture\n UserKnownHostsFile {json.dumps(host["known_hosts"])}\n GlobalKnownHostsFile /dev/null\n')
    return ssh_discovery.profile('selected',config),{p:p.read_bytes() for p in (config,child)}


def test_enrollment_remembers_identity_for_later_snapshot_without_changing_config(authorization,tmp_path):
    host,public,name,_,write,docker,_=authorization
    profile,original=configured(host,tmp_path)
    result=asyncio.run(access_setup.enroll(profile,public,lambda _:True,tmp_path/'receipts'))
    assert result['status']=='installed_and_verified' and result['identity_saved'],result
    key=access_preview.public_key(public)
    # The configured bootstrap key can no longer authenticate. The ordinary
    # read-only path must reuse the verified choice without another key question.
    write(key['public_line']+'\n')
    snapshot=asyncio.run(hosts.fetch_host(profile))
    assert snapshot['status']=='connected' and snapshot['identity_fingerprint']==key['fingerprint'],snapshot
    assert snapshot['snapshot']['node_id']==host['node_id']
    assert access_setup.choose_key(profile)==key
    assert all(p.read_bytes()==data for p,data in original.items())
    assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==key['public_line']+'\n'


def test_missing_selected_private_key_cannot_fall_back_to_working_config_identity(authorization,tmp_path):
    host,public,_,_,_,_,_=authorization
    profile,_=configured(host,tmp_path)
    assert asyncio.run(access_setup.enroll(profile,public,lambda _:True,tmp_path/'receipts'))['identity_saved']
    Path(str(public)[:-4]).rename(tmp_path/'unavailable_private_key')
    result=asyncio.run(hosts.fetch_host(profile))
    assert result['status']=='authentication_error' and result['snapshot'] is None,result
    assert 'Selected key' in result['reason'] and 'does not add agent keys' in result['reason']


def test_nonexistent_selected_identity_does_not_enable_default_or_config_fallback(authorization,tmp_path):
    host,_,_,_,_,_,_=authorization;profile,_=configured(host,tmp_path)
    with access_transport.connection(profile,key_only=tmp_path/'missing') as (argv,env,root):
        status,_,_=asyncio.run(hosts.exchange(argv,b'',5,env))
        assert status!=0
        assert b'using "publickey"' not in (root/'hop-0.log').read_bytes()


def test_only_matching_public_identity_is_used_from_a_temporary_agent(authorization,tmp_path,monkeypatch):
    host,public,_,_,_,_,_=authorization;profile,_=configured(host,tmp_path)
    child=tmp_path/'identity choices.conf'
    child.write_text(child.read_text().replace(' IdentityAgent none\n',''))
    with tempfile.TemporaryDirectory(prefix='pimux-agent-',dir='/tmp') as directory:
        socket=Path(directory)/'socket'
        agent=subprocess.Popen(['/usr/bin/ssh-agent','-D','-a',str(socket)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            deadline=time.monotonic()+3
            while not socket.exists():
                assert agent.poll() is None and time.monotonic()<deadline
                time.sleep(.01)
            monkeypatch.setenv('SSH_AUTH_SOCK',str(socket))
            for path in (host['identity_file'],str(public)[:-4]):
                subprocess.run(['/usr/bin/ssh-add',path],check=True,capture_output=True,timeout=5)
            assert asyncio.run(access_setup.enroll(profile,public,lambda _:True,tmp_path/'receipts'))['identity_saved']
            Path(str(public)[:-4]).rename(tmp_path/'private_not_readable_by_path')
            result=asyncio.run(hosts.fetch_host(profile))
            assert result['status']=='connected' and result['identity_fingerprint']==access_preview.public_key(public)['fingerprint'],result
        finally:
            agent.terminate();agent.wait(timeout=3)


@pytest.mark.parametrize('correct_phrase',[True,False])
def test_encrypted_selected_key_prompts_on_terminal_and_batch_failure_is_actionable(authorization,tmp_path,correct_phrase):
    host,_,_,_,_,_,_=authorization;profile,_=configured(host,tmp_path)
    phrase='Temporary-test-passphrase'
    keypath=tmp_path/'encrypted fixture key'
    subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N',phrase,'-f',str(keypath)],check=True)
    public=Path(str(keypath)+'.pub')
    # Only fixture credentials travel through this PTY. Product code receives
    # no passphrase argv/config and never inserts a key into an agent.
    script='''import asyncio,json,os,sys
sys.path.insert(0,sys.argv[1])
import access_setup,hosts
host=json.loads(sys.argv[2]);public=sys.argv[3]
result=hosts.run_operation(access_setup.enroll(host,public,lambda _:True,sys.argv[4],tty=os.ttyname(0)))
print(json.dumps(result),flush=True)
if result['status']!='installed_and_verified': raise SystemExit(1)
print(json.dumps(hosts.run_operation(hosts.fetch_host(host))),flush=True)
print(json.dumps(hosts.run_operation(hosts.fetch_host(host,tty=os.ttyname(0)))),flush=True)
'''
    pid,terminal=pty.fork();captured=bytearray();prompts=0;seen=0;status=None
    if pid==0:
        os.execve(sys.executable,[sys.executable,'-c',script,str(Path(hosts.__file__).parent),json.dumps(profile),str(public),str(tmp_path/'receipts')],
                  {**os.environ,'SSH_AUTH_SOCK':''})
    try:
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if select.select([terminal],[],[],.1)[0]:
                try: chunk=os.read(terminal,65536)
                except OSError as error:
                    if error.errno!=errno.EIO: raise
                    break
                if not chunk: break
                captured.extend(chunk)
                if b'passphrase' in bytes(captured[seen:]).lower() and b':' in bytes(captured[seen:]):
                    prompts+=1;assert prompts<=2
                    os.write(terminal,(phrase if correct_phrase or prompts==1 else 'incorrect').encode()+b'\n');seen=len(captured)
            ended,status=os.waitpid(pid,os.WNOHANG)
            if ended: pid=None;break
        if pid is not None:
            ended,status=reap_until_deadline(pid,deadline)
            if ended: pid=None
        assert pid is None,bytes(captured).decode(errors='replace')
        assert phrase.encode() not in captured and prompts==2
        rows=[json.loads(line) for line in bytes(captured).decode().splitlines() if line.startswith('{')]
        assert rows[0]['status']=='installed_and_verified' and rows[0]['identity_saved'],rows
        assert rows[1]['status']=='authentication_error' and 'interactive terminal' in rows[1]['reason'],rows
        assert rows[2]['status']==('connected' if correct_phrase else 'authentication_error'),rows
        if correct_phrase: assert rows[2]['identity_fingerprint']==access_preview.public_key(public)['fingerprint']
    finally:
        if pid is not None: os.kill(pid,signal.SIGTERM);os.waitpid(pid,0)
        os.close(terminal)
