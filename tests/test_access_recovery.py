"""Adversarial recovery: concurrent editors and immutable operation identity."""
import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path

import pytest
import access_agent
import access_setup
import access_transport
import ssh_discovery


@pytest.fixture
def synthetic_key(tmp_path):
    algorithm=b'ssh-ed25519'
    blob=len(algorithm).to_bytes(4,'big')+algorithm+(32).to_bytes(4,'big')+b'F'*32
    return {'path':str(tmp_path/'fictional.pub'),'algorithm':'ssh-ed25519',
            'fingerprint':access_agent.fingerprint(blob),'public_line':'ssh-ed25519 '+base64.b64encode(blob).decode()}


@pytest.mark.parametrize('edit',['append','delete_entry','replace_file','unlink_file'])
def test_recovery_cannot_overwrite_edits_after_its_last_read(tmp_path,synthetic_key,monkeypatch,edit):
    store=access_agent.Store(tmp_path);store.directory.mkdir(mode=0o700)
    original=b'# existing A\n# existing B\n';store.path.write_bytes(original);store.path.chmod(0o600)
    operation='a'*32
    assert store.apply(operation,synthetic_key['public_line'],access_agent.digest(original))['state']=='applied'
    read=store.read;observed=[]
    def concurrent_editor():
        snapshot=read()
        if edit=='append':
            with store.path.open('ab') as stream: stream.write(b'# independently added C\n')
        elif edit=='delete_entry': store.path.write_bytes(snapshot.replace(b'# existing A\n',b''))
        elif edit=='replace_file':
            replacement=tmp_path/'replacement';replacement.write_bytes(b'# entirely new owner-maintained file\n')
            os.replace(replacement,store.path)
        else: store.path.unlink()
        observed.append(store.path.read_bytes() if store.path.exists() else None)
        return snapshot
    monkeypatch.setattr(store,'read',concurrent_editor)
    result=store.rollback(operation)
    assert result['state']=='rollback_requires_review'
    assert observed and (store.path.read_bytes() if store.path.exists() else None)==observed[-1]


def test_rollback_never_enters_the_check_to_replace_race(tmp_path,synthetic_key,monkeypatch):
    store=access_agent.Store(tmp_path);store.directory.mkdir(mode=0o700);store.path.write_bytes(b'# preserve\n')
    assert store.apply('a'*32,synthetic_key['public_line'],access_agent.digest(store.read()))['state']=='applied'
    before=store.path.read_bytes();inode=store.path.stat().st_ino
    original=os.replace
    def no_authorization_replace(source,target):
        assert Path(target)!=store.path,'Rollback must not replace a shared authorized_keys file'
        return original(source,target)
    monkeypatch.setattr(os,'replace',no_authorization_replace)
    result=store.rollback('a'*32)
    assert result['state']=='rollback_requires_review'
    assert store.path.read_bytes()==before and store.path.stat().st_ino==inode


@pytest.fixture
def pending(tmp_path,synthetic_key,monkeypatch):
    config=tmp_path/'config';known=tmp_path/'known_hosts'
    known.write_text('# originally trusted server A\n')
    config.write_text(f'Host fictional\n HostName fictional.invalid\n User fixture\n UserKnownHostsFile "{known}"\n')
    host=ssh_discovery.profile('fictional',config);operation='b'*32
    fingerprint={'algorithm':'ssh-ed25519','fingerprint':'SHA256:'+'A'*43}
    review=dict(version=1,operation=operation,account='fixture',uid=1000,hostname='server-a',node_id='a'*32,
                mode='openssh',fingerprint=synthetic_key['fingerprint'],file_digest='d'*64,present=True,restricted=False,token='e'*64)
    expected={**review,'host_key':fingerprint,'configuration_digest':access_transport.configuration_digest(host)}
    root=tmp_path/'receipts';root.mkdir(mode=0o700);path=root/(operation+'.json')
    record={'operation':operation,'host':host,'key':synthetic_key,'review':expected,'status':'pending'}
    path.write_text(json.dumps(record));path.chmod(0o600)
    monkeypatch.setattr(access_setup,'public_key',lambda _path:synthetic_key)
    return host,synthetic_key,review,fingerprint,path,known


def mock_review(monkeypatch,review,fingerprint,state,verify_result=True):
    sent=[];verified=[]
    @contextlib.contextmanager
    def connection(*_args,**_kwargs): yield [],{},Path('/fictional-unused-log-directory')
    class Channel:
        def __init__(self,*_args): pass
        def __enter__(self): return self
        def __exit__(self,*_args): pass
        async def send(self,data): sent.append(data)
        async def receive(self): return {'type':'review','review':review,'operation_state':{'state':state}}
    async def verify(*args): verified.append(args);return verify_result
    monkeypatch.setattr(access_setup,'connection',connection);monkeypatch.setattr(access_setup,'Channel',Channel)
    monkeypatch.setattr(access_setup,'verified_host_key',lambda _root:fingerprint);monkeypatch.setattr(access_setup,'verify',verify)
    return sent,verified


@pytest.mark.parametrize('change',['node_id','host_key','account','uid','fingerprint'])
@pytest.mark.parametrize('present',[True,False])
@pytest.mark.parametrize('state',['not_started','applied','changed_requires_review'])
def test_pending_target_drift_cannot_succeed_or_clear_the_original_receipt(pending,monkeypatch,change,present,state):
    host,key,review,host_key,receipt,known=pending
    before=receipt.read_bytes();review={**review,'present':present}
    if change=='host_key': host_key={**host_key,'fingerprint':'SHA256:'+'B'*43}
    elif change=='uid': review[change]=1001
    elif change=='fingerprint': review[change]='SHA256:'+'C'*43
    else: review[change]='c'*32 if change=='node_id' else 'different_account'
    original_digest=access_transport.configuration_digest(host)
    known.write_text('# independently trusted server B; configuration text unchanged\n')
    assert access_transport.configuration_digest(host)==original_digest
    sent,verified=mock_review(monkeypatch,review,host_key,state)
    def confirm(_review): pytest.fail('Drifted pending target must not reach fresh authorization')
    result=asyncio.run(access_setup.enroll(host,key['path'],confirm,receipt.parent))
    assert result['status']=='outcome_requires_review' and result['changed'] is None
    assert receipt.read_bytes()==before and not verified
    assert not any(b'"apply"' in packet for packet in sent)


@pytest.mark.parametrize('mode,state,verification',[('unknown','applied',True),('tailscale_ssh_policy','applied',True),
    ('openssh','applied',False),('openssh','partial_write',True),('openssh','changed_requires_review',True)])
def test_nonterminal_fast_paths_preserve_pending_recovery(pending,monkeypatch,mode,state,verification):
    host,key,review,host_key,receipt,_=pending;before=receipt.read_bytes()
    sent,_=mock_review(monkeypatch,{**review,'mode':mode},host_key,state,verification)
    result=asyncio.run(access_setup.enroll(host,key['path'],lambda _:pytest.fail('No apply'),receipt.parent))
    assert result['status']=='outcome_requires_review' and result['changed'] is None
    assert receipt.read_bytes()==before and not any(b'"apply"' in packet for packet in sent)


@pytest.mark.parametrize('change',['configuration','selected_key'])
def test_pending_configuration_or_key_change_stops_before_connection(pending,monkeypatch,change):
    host,key,_,_,receipt,_=pending;before=receipt.read_bytes()
    if change=='configuration': Path(host['ssh_config']).write_text('Host fictional\n HostName another.invalid\n')
    else: monkeypatch.setattr(access_setup,'public_key',lambda _path:{**key,'fingerprint':'different'})
    monkeypatch.setattr(access_setup,'connection',lambda *_args,**_kwargs:pytest.fail('No connection'))
    result=asyncio.run(access_setup.enroll(host,key['path'],lambda _:True,receipt.parent,operation='b'*32))
    assert result['status']=='outcome_requires_review' and receipt.read_bytes()==before


def test_same_bound_target_can_resolve_a_pending_operation(pending,monkeypatch):
    host,key,review,host_key,receipt,_=pending
    original=json.loads(receipt.read_text())
    sent,verified=mock_review(monkeypatch,review,host_key,'applied',True)
    result=asyncio.run(access_setup.enroll(host,key['path'],lambda _:pytest.fail('No new write'),receipt.parent))
    updated=json.loads(receipt.read_text())
    assert result['status']=='verified_existing' and len(verified)==1
    assert updated['review']==original['review'] and updated['status']=='verified_existing'
    assert not any(b'"apply"' in packet for packet in sent)
