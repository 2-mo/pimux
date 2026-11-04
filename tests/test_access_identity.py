"""Only synthetic configuration, temporary public keys and offline ssh -G."""
import asyncio
import json
import os
from pathlib import Path
import subprocess

import pytest
import access_identity
import access_preview
import access_setup
import access_transport
import hosts
import ssh_discovery


@pytest.fixture
def selected(tmp_path):
    keypath=tmp_path/'selected key'
    subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-f',str(keypath)],check=True)
    key=access_preview.public_key(str(keypath)+'.pub')
    config=tmp_path/'ssh config'; child=tmp_path/'identities.conf'
    child.write_text('Host *\n IdentityFile /fictional/first\n IdentityFile=/fictional/second\n CertificateFile /fictional/certificate\n')
    config.write_text(f'Include {json.dumps(str(child))}\nMatch originalhost selected\n User selected_user\n'
                      'Host selected\n HostName 127.0.0.1\n ProxyJump gateway\nHost gateway\n HostName 127.0.0.1\n User jump_user\n')
    host=ssh_discovery.profile('selected',config)
    review={'configuration_digest':access_transport.configuration_digest(host),'node_id':'a'*32,'account':'selected_user','uid':1000,
            'host_key':{'algorithm':'ssh-ed25519','fingerprint':'SHA256:fictional'}}
    return host,key,review,child


def evaluated(argv,env):
    output=subprocess.run(argv,env=env,text=True,capture_output=True,timeout=5,check=True).stdout
    result={}
    for line in output.splitlines():
        name,value=line.split(' ',1);result.setdefault(name,[]).append(value)
    return result


def test_destination_only_projection_preserves_match_and_jump_identities(selected):
    host,key,_,child=selected
    before={p:p.read_bytes() for p in (Path(host['ssh_config']),child)}
    with access_transport.connection(host,key_only=access_identity.identity(key)) as (argv,env,root):
        target=evaluated([argv[0],'-G',*argv[1:]],env)
        assert target['identityfile']==[str(access_identity.identity(key)),'none']
        assert target['certificatefile']==['none']
        assert target['user']==['selected_user'] and target['proxyjump']==['gateway']
        assert target['identitiesonly']==['yes'] and target['passwordauthentication']==['no']
        projected=argv[argv.index('-F')+1]
        # Simulate exactly the implicit jump client's -F inheritance. These
        # offline evaluations run the real wrapper and native OpenSSH parser.
        for depth in (1,2):
            jump=evaluated([argv[0],'-G','-F',projected,'gateway'],{**env,'PIMUX_SSH_DEPTH':str(depth)})
            assert jump['identityfile']==['/fictional/first','/fictional/second']
            assert jump['certificatefile']==['/fictional/certificate'] and jump['user']==['jump_user']
            assert jump['stricthostkeychecking']==['true'] and jump['permitlocalcommand']==['no']
    assert all(p.read_bytes()==data for p,data in before.items())


def test_record_reuses_exact_public_identity_and_does_not_read_private_bytes(selected,monkeypatch):
    host,key,review,_=selected
    private=access_identity.identity(key)
    original=Path.open
    def guarded(path,*args,**kwargs):
        assert path!=private,'PiMux must not read private key bytes'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',guarded)
    access_identity.remember(host,key,review)
    assert access_identity.load(host)['key']==key
    assert access_setup.choose_key(host)==key
    assert access_identity.location(host).stat().st_mode&0o777==0o600
    assert access_identity.directory().stat().st_mode&0o777==0o700
    other=ssh_discovery.profile('other',host['ssh_config'])
    assert access_identity.load(other) is None
    access_identity.forget(host)
    assert access_identity.load(host) is None


@pytest.mark.parametrize('change',['config','public','missing_public','permissions','symlink','corrupt'])
def test_stale_or_unsafe_selection_never_connects_or_falls_back(selected,change,monkeypatch,tmp_path):
    host,key,review,child=selected
    access_identity.remember(host,key,review);path=access_identity.location(host)
    if change=='config': child.write_text(child.read_text()+'# changed\n')
    elif change=='public': Path(key['path']).write_text('invalid public key\n')
    elif change=='missing_public': Path(key['path']).unlink()
    elif change=='permissions': path.chmod(0o644)
    elif change=='symlink':
        other=tmp_path/'record';path.rename(other);path.symlink_to(other)
    else: path.write_text('{}')
    async def forbidden(*args,**kwargs): pytest.fail('Stale identity must fail before SSH starts')
    monkeypatch.setattr(hosts,'exchange',forbidden)
    result=asyncio.run(hosts.fetch_host(host))
    assert result['status']=='identity_selection_error' and result['snapshot'] is None
    assert 'identity-reset' in result['reason']


@pytest.mark.parametrize('field',['node_id','account','host_key'])
def test_response_binding_rejects_a_different_trusted_target(selected,field):
    host,key,review,_=selected;access_identity.remember(host,key,review)
    record=access_identity.load(host)
    snapshot={'node_id':review['node_id'],'account':{'name':review['account'],'uid':review['uid']}}
    hostkey=review['host_key']
    assert access_identity.matches(record,snapshot,hostkey)
    if field=='host_key': hostkey={**hostkey,'fingerprint':'SHA256:another'}
    elif field=='account': snapshot['account']={'name':'other','uid':1001}
    else: snapshot[field]='b'*32
    assert not access_identity.matches(record,snapshot,hostkey)


def test_inherited_jump_override_is_not_used(selected,monkeypatch):
    host,_,_,_=selected
    monkeypatch.setenv('PIMUX_SSH_JUMP_CONFIG','/fictional/uninspected')
    with access_transport.connection(host) as (_,env,_):
        assert 'PIMUX_SSH_JUMP_CONFIG' not in env


@pytest.mark.parametrize('path',['relative_key','/tmp/key%h','/tmp/${HOME}/key','/tmp/key\nnext'])
def test_selected_identity_never_expands_a_different_path(selected,path):
    host,_,_,_=selected
    with pytest.raises(ValueError,match='absolute literal path'):
        with access_transport.connection(host,key_only=path): pytest.fail('Unsafe identity admitted')


def test_saved_identity_failure_does_not_change_verified_remote_result(selected,monkeypatch,tmp_path):
    host,key,review,_=selected
    async def verified(*args):
        return access_setup.verified_result({'status':'verified_existing','changed':False},key,review)
    monkeypatch.setattr(access_setup,'_enroll',verified)
    def unavailable(*args): raise OSError('fixture storage unavailable')
    monkeypatch.setattr(access_identity,'remember',unavailable)
    result=asyncio.run(access_setup.enroll(host,key['path'],lambda _:True,tmp_path/'receipts'))
    assert result['status']=='verified_existing' and result['identity_saved'] is False
    assert '_verified_identity' not in result
