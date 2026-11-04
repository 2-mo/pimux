"""Real enrollment is confined to disposable SSH fixture containers."""
import asyncio
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import time
import uuid

import pytest
import access_preview
import access_setup
import ssh_discovery
from tests.test_hosts_ssh import endpoints

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def authorization(endpoints,tmp_path,request):
    manifest,mode,docker=endpoints
    label=getattr(request,'param','alpha')
    name=manifest['containers'][label];host=next(row for row in manifest['hosts'] if row['host_id']==label)
    before=docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')
    path=tmp_path/'proposed_key'
    subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-f',str(path)],check=True)
    public=Path(str(path)+'.pub')
    def write(data):
        docker('exec',name,'python3','-c','from pathlib import Path; import sys; Path("/home/fixture/.ssh/authorized_keys").write_text(sys.argv[1])',data)
    try: yield host,public,name,before,write,docker,manifest
    finally:
        write(before)
        docker('exec',name,'python3','-c','from pathlib import Path; import shutil; p=Path("/home/fixture/.ssh/.pimux-enrollment"); shutil.rmtree(p) if p.exists() else None')


def test_real_install_verify_repeat_and_restricted_duplicate(authorization,tmp_path):
    host,public,name,before,write,docker,_=authorization
    confirms=[]
    def approve(review): confirms.append(review);return True
    result=asyncio.run(access_setup.enroll(host,public,approve,tmp_path/'receipts'))
    assert result['status']=='installed_and_verified',result
    assert len(confirms)==1 and confirms[0]['account']=='fixture' and confirms[0]['host_key']
    after=docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')
    assert after.startswith(before)
    assert after.count(access_preview.public_key(public)['public_line'])==1
    result=asyncio.run(access_setup.enroll(host,public,lambda _:pytest.fail('Existing key must not ask for another write'),tmp_path/'receipts'))
    assert result['status']=='verified_existing',result
    assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==after
    restricted=before+'restrict,command="echo constrained" '+access_preview.public_key(public)['public_line']+' limited\n'
    write(restricted)
    result=asyncio.run(access_setup.enroll(host,public,lambda _:pytest.fail('Restricted key cannot be broadened'),tmp_path/'receipts'))
    assert result['restricted'] and not result['changed'],result
    assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==restricted


@pytest.mark.parametrize('change',['cancel','configuration','public_key','remote_authorization'])
def test_cancel_and_changed_confirmation_inputs_never_grant_stale_access(authorization,tmp_path,change):
    host,public,name,before,write,docker,_=authorization
    config=tmp_path/'config'
    config.write_text(f'Host target\n HostName 127.0.0.1\n Port {host["port"]}\n User fixture\n'
                      f' IdentityFile {json.dumps(host["identity_file"])}\n UserKnownHostsFile {json.dumps(host["known_hosts"])}\n GlobalKnownHostsFile /dev/null\n')
    selected=ssh_discovery.profile('target',config)
    expected=before
    def confirm(_review):
        nonlocal expected
        if change=='cancel': return False
        if change=='configuration': config.write_text(config.read_text()+'Host target\n HostName fictional.invalid\n')
        if change=='public_key': public.write_text(Path(host['identity_file']+'.pub').read_text())
        if change=='remote_authorization': expected=before+'# concurrent owner update\n';write(expected)
        return True
    result=asyncio.run(access_setup.enroll(selected,public,confirm,tmp_path/'receipts'))
    assert result['status']==('cancelled' if change=='cancel' else 'changed_requires_confirmation'),result
    assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==expected


@pytest.mark.parametrize('edit',['none','append','delete','replace'])
def test_key_only_failure_retains_evidence_and_never_rewrites_other_authorizations(authorization,tmp_path,monkeypatch,edit):
    host,public,name,before,_,docker,_=authorization
    observed=[]
    async def fail(*_args):
        if edit!='none':
            docker('exec',name,'runuser','-u','fixture','--','python3','-c','from pathlib import Path; import os,sys; p=Path("/home/fixture/.ssh/authorized_keys"); d=p.read_bytes(); mode=sys.argv[1]; replacement=p.with_name("fixture-replacement"); replacement.write_bytes(b"# independent replacement\\n") if mode=="replace" else None; os.replace(replacement,p) if mode=="replace" else p.write_bytes(d+b"# independent addition\\n" if mode=="append" else d.split(b"\\n",1)[1])',edit)
        observed.append(docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys'))
        return False
    monkeypatch.setattr(access_setup,'verify',fail)
    result=asyncio.run(access_setup.enroll(host,public,lambda _:True,tmp_path/'receipts'))
    assert result['status']=='outcome_requires_review' and result['recovery']=='rollback_requires_review' and result['changed'] is None,result
    assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==observed[0]
    assert json.loads((tmp_path/'receipts'/(result['operation']+'.json')).read_text())['status']=='outcome_requires_review'


@pytest.mark.parametrize('authorization',['beta'],indirect=True)
@pytest.mark.parametrize('point',['after_append','before_append'])
def test_real_disconnect_after_append_reconciles_before_any_retry(authorization,tmp_path,point):
    host,public,name,before,_,docker,_=authorization
    def mode(value): docker('exec',name,'python3','-c','from pathlib import Path; import sys; Path("/tmp/fixture-mode").write_text(sys.argv[1])',value)
    mode('enrollment_drop_'+point)
    confirmations=[]
    def confirm(review): confirmations.append(review);return True
    result=asyncio.run(access_setup.enroll(host,public,confirm,tmp_path/'receipts'))
    if point=='after_append': assert result['status']=='installed_and_verified_after_reconnect',result
    else:
        assert result['status']=='outcome_requires_review' and result['changed'] is None,result
        assert len(confirmations)==1 and docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==before
        mode('normal')
        result=asyncio.run(access_setup.enroll(host,public,confirm,tmp_path/'receipts'))
        assert result['status']=='installed_and_verified' and len(confirmations)==2,result
    after=docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')
    assert after.startswith(before) and after.count(access_preview.public_key(public)['public_line'])==1


@pytest.mark.parametrize('create_key',[False,'plain','encrypted'])
@pytest.mark.parametrize('correct_password',[True,False])
def test_terminal_password_is_masked_and_one_confirmation_installs_and_verifies(authorization,tmp_path,create_key,correct_password):
    host,public,name,before,_,docker,_=authorization
    secret='Fixture-'+uuid.uuid4().hex
    phrase='Key-'+uuid.uuid4().hex if create_key=='encrypted' else ''
    binary=os.environ.get('PIMUX_FIXTURE_DOCKER','docker')
    subprocess.run([binary,'exec','-i',name,'chpasswd'],input='fixture:'+secret+'\n',text=True,capture_output=True,check=True,timeout=10)
    original=docker('exec',name,'cat','/etc/ssh/sshd_config')
    def config(value):
        docker('exec',name,'python3','-c','from pathlib import Path; import os,signal,sys; Path("/etc/ssh/sshd_config").write_text(sys.argv[1]); os.kill(int(Path("/run/sshd/fixture.pid").read_text()),signal.SIGHUP)',value)
    pid=None;terminal=None;captured=bytearray();passwords=confirmations=0
    try:
        config(original.replace('PasswordAuthentication no','PasswordAuthentication yes'))
        selected={**host,'identity_file':str(tmp_path/'absent_initial_identity')}
        inventory=tmp_path/'hosts.json';inventory.write_text(json.dumps({'version':1,'hosts':[selected]}))
        home=tmp_path/'home';home.mkdir(mode=0o700)
        pid,terminal=pty.fork()
        if pid==0:
            env={**os.environ,'HOME':str(home),'SSH_AUTH_SOCK':''}
            argv=[sys.executable,str(ROOT/'lib/hosts.py'),'--config',str(inventory),'access-setup','alpha']
            if not create_key: argv+=['--key',str(public)]
            os.execve(sys.executable,argv,env)
        deadline=time.monotonic()+35;seen=0;status=None
        while time.monotonic()<deadline:
            if select.select([terminal],[],[],.1)[0]:
                try: chunk=os.read(terminal,65536)
                except OSError: break
                captured.extend(chunk)
                current=bytes(captured[seen:]).lower()
                if b'enter passphrase' in current or b'enter same passphrase' in current:
                    os.write(terminal,phrase.encode()+b'\n');seen=len(captured)
                elif b'password:' in current:
                    passwords+=1;assert passwords==1
                    os.write(terminal,(secret if correct_password else 'incorrect-fixture-only-password').encode()+b'\n');seen=len(captured)
                elif b'authorize this exact target and key now? [yes/n]' in current:
                    confirmations+=1;os.write(terminal,b'yes\n');seen=len(captured)
            ended,status=os.waitpid(pid,os.WNOHANG)
            if ended: pid=None;break
        if pid is not None:
            ended,status=os.waitpid(pid,os.WNOHANG)
            if ended: pid=None
        assert secret.encode() not in captured
        if phrase: assert phrase.encode() not in captured
        assert passwords==1 and confirmations==int(correct_password),bytes(captured).decode(errors='replace')
        assert pid is None,bytes(captured).decode(errors='replace')
        if correct_password:
            assert os.waitstatus_to_exitcode(status)==0 and b'installed_and_verified' in captured,bytes(captured).decode(errors='replace')
            assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys').startswith(before)
            if create_key:
                retained=list((home/'.ssh').glob('*.pub'));assert len(retained)==1
                assert retained[0].with_suffix('').stat().st_mode&0o777==0o600
        else:
            assert os.waitstatus_to_exitcode(status)!=0 and b'authentication denied' in captured.lower(),bytes(captured).decode(errors='replace')
            assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==before
            assert not list(home.glob('.pimux-key-review-*'))
    finally:
        if pid is not None:
            os.kill(pid,signal.SIGTERM);os.waitpid(pid,0)
        if terminal is not None: os.close(terminal)
        config(original)
        docker('exec',name,'usermod','-p','x','fixture')


@pytest.mark.parametrize('authorization',['beta'],indirect=True)
def test_confirmed_enrollment_through_existing_strict_proxyjump(authorization,tmp_path):
    host,public,name,before,write,docker,manifest=authorization
    gateway=manifest['containers']['alpha']
    address=docker('inspect','-f','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',name).strip()
    target_key=' '.join(docker('exec',name,'cat','/fixture/host_key.pub').split()[:2])
    known=tmp_path/'known hosts';known.write_text(Path(host['known_hosts']).read_text()+f'[{address}]:2222 {target_key}\n')
    config=tmp_path/'jump config'
    config.write_text(f'Host gateway\n HostName 127.0.0.1\n Port {manifest["hosts"][0]["port"]}\n StrictHostKeyChecking no\n'
       f'Host target\n HostName {address}\n Port 2222\n ProxyJump gateway\n'
       f'Host *\n User fixture\n IdentityFile {json.dumps(host["identity_file"])}\n'
       f' UserKnownHostsFile {json.dumps(str(known))}\n GlobalKnownHostsFile /dev/null\n IdentitiesOnly yes\n IdentityAgent none\n')
    original=docker('exec',gateway,'cat','/etc/ssh/sshd_config')
    def change(value):
        docker('exec',gateway,'python3','-c','from pathlib import Path; import os,signal,sys; Path("/etc/ssh/sshd_config").write_text(sys.argv[1]); os.kill(int(Path("/run/sshd/fixture.pid").read_text()),signal.SIGHUP)',value)
    try:
        change(original.replace('AllowTcpForwarding no','AllowTcpForwarding local')+f'\nPermitOpen {address}:2222\n')
        selected=ssh_discovery.profile('target',config)
        result=asyncio.run(access_setup.enroll(selected,public,lambda _:True,tmp_path/'receipts'))
        assert result['status']=='installed_and_verified',result
        assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys').startswith(before)
        # Target only accepts the chosen key; gateway only accepts its original
        # bootstrap key. A leaked destination override breaks this real jump.
        write(access_preview.public_key(public)['public_line']+'\n')
        import hosts
        snapshot=asyncio.run(hosts.fetch_host(selected))
        assert snapshot['status']=='connected' and snapshot['identity_fingerprint']==access_preview.public_key(public)['fingerprint'],snapshot
    finally: change(original)


def test_termination_while_reviewing_confirmation_is_bounded_and_does_not_write(authorization,tmp_path):
    host,public,name,before,_,docker,_=authorization
    inventory=tmp_path/'hosts.json';inventory.write_text(json.dumps({'version':1,'hosts':[host]}))
    home=tmp_path/'home';home.mkdir(mode=0o700)
    pid,terminal=pty.fork();captured=bytearray()
    if pid==0:
        os.execve(sys.executable,[sys.executable,str(ROOT/'lib/hosts.py'),'--config',str(inventory),'access-setup','alpha','--key',str(public)],{**os.environ,'HOME':str(home)})
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and b'Authorize this exact target' not in captured:
            if select.select([terminal],[],[],.1)[0]: captured.extend(os.read(terminal,65536))
        assert b'Authorize this exact target' in captured,bytes(captured)
        children=subprocess.run(['pgrep','-P',str(pid)],capture_output=True,text=True).stdout.split()
        assert children
        os.kill(pid,signal.SIGTERM)
        deadline=time.monotonic()+3;ended=0
        while time.monotonic()<deadline:
            ended,status=os.waitpid(pid,os.WNOHANG)
            if ended: break
            time.sleep(.02)
        assert ended and os.waitstatus_to_exitcode(status)==143
        pid=None
        for child in children:
            with pytest.raises(ProcessLookupError): os.kill(int(child),0)
        assert docker('exec',name,'cat','/home/fixture/.ssh/authorized_keys')==before
        assert not (home/'.local/state/pimux/enrollment').exists()
    finally:
        if pid is not None:
            os.kill(pid,signal.SIGKILL);os.waitpid(pid,0)
        os.close(terminal)


def test_real_pending_alias_route_change_preserves_original_operation(endpoints,tmp_path,monkeypatch):
    import selectors
    import socket
    import socketserver
    import threading
    from access_transport import Channel,connection,configuration_digest,verified_host_key
    manifest,_,docker=endpoints
    alpha,beta=manifest['hosts'];routing=[alpha['port']]
    class Forward(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection(('127.0.0.1',routing[0]),timeout=5) as upstream, selectors.DefaultSelector() as selector:
                selector.register(self.request,selectors.EVENT_READ,upstream)
                selector.register(upstream,selectors.EVENT_READ,self.request)
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    for selected,_ in selector.select(.1):
                        chunk=selected.fileobj.recv(65536)
                        if not chunk: return
                        selected.data.sendall(chunk)
    class Router(socketserver.ThreadingTCPServer):
        daemon_threads=True
    with Router(('127.0.0.1',0),Forward) as router:
        thread=threading.Thread(target=router.serve_forever,daemon=True);thread.start()
        known=tmp_path/'known_hosts';config=tmp_path/'config'
        def trust(label):
            public=' '.join(docker('exec',manifest['containers'][label],'cat','/fixture/host_key.pub').split()[:2])
            known.write_text(f'[127.0.0.1]:{router.server_address[1]} {public}\n')
        trust('alpha')
        config.write_text(f'Host selected\n HostName 127.0.0.1\n Port {router.server_address[1]}\n User fixture\n'
                          f' IdentityFile {json.dumps(alpha["identity_file"])}\n UserKnownHostsFile {json.dumps(str(known))}\n'
                          ' GlobalKnownHostsFile /dev/null\n IdentitiesOnly yes\n IdentityAgent none\n')
        host=ssh_discovery.profile('selected',config);key=access_preview.public_key(alpha['identity_file']+'.pub')
        operation='f'*32;root=tmp_path/'receipts';receipt=root/(operation+'.json')
        async def original_review():
            with connection(host) as (argv,env,logs),Channel(argv,env,5) as channel:
                await channel.send(access_setup.request(operation,key));reply=await channel.receive()
                review=access_setup.validate_review(reply,operation,key,host,verified_host_key(logs))
                await channel.send(access_setup.command(action='cancel'))
                review['configuration_digest']=configuration_digest(host)
                assert review['node_id']==alpha['node_id']
                access_setup.save_receipt(receipt,{'operation':operation,'host':host,'key':key,'review':review,'status':'pending'})
                import access_identity
                access_identity.remember(host,key,review)
        try:
            asyncio.run(original_review());before=receipt.read_bytes();original_digest=configuration_digest(host)
            routing[0]=beta['port'];trust('beta')
            assert configuration_digest(host)==original_digest
            import hosts
            snapshot=asyncio.run(hosts.fetch_host(host))
            assert snapshot['status']=='identity_selection_error' and snapshot['snapshot'] is None,snapshot
            seen=[];validate=access_setup.validate_review
            def capture(*args):
                review=validate(*args);seen.append(review);return review
            monkeypatch.setattr(access_setup,'validate_review',capture)
            async def no_verify(*_args): pytest.fail('Different target must not enter existing-key success path')
            monkeypatch.setattr(access_setup,'verify',no_verify)
            result=asyncio.run(access_setup.enroll(host,key['path'],lambda _:pytest.fail('No new grant'),root))
            assert seen[-1]['node_id']==beta['node_id'] and seen[-1]['present']
            assert result['status']=='outcome_requires_review' and result['reason']=='original_target_identity_changed',result
            assert receipt.read_bytes()==before
        finally:
            router.shutdown();thread.join(timeout=2)
            assert not thread.is_alive()
