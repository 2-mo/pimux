"""Confirmed enrollment logic using only temporary directories and fixture keys."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
import access_agent
import access_preview
import access_setup
import ssh_discovery


@pytest.fixture
def key(tmp_path):
    path=tmp_path/'temporary_key'
    subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-f',str(path)],check=True)
    return access_preview.public_key(Path(str(path)+'.pub'))


def test_append_repeat_reconcile_and_declined_rollback_preserve_authorizations(tmp_path,key):
    store=access_agent.Store(tmp_path)
    original=b'# existing unrelated authorizations\n'
    store.directory.mkdir(mode=0o700);store.path.write_bytes(original);store.path.chmod(0o600)
    operation='a'*32
    assert store.apply(operation,key['public_line'],access_agent.digest(original))['state']=='applied'
    after=store.read()
    assert after.startswith(original) and after.count(key['public_line'].encode())==1
    assert store.path.stat().st_mode&0o777==0o600
    assert store.apply(operation,key['public_line'],access_agent.digest(original))['state']=='applied'
    assert store.read()==after
    assert store.apply('b'*32,key['public_line'],access_agent.digest(after))['state']=='already_listed'
    assert store.rollback(operation)['state']=='rollback_requires_review' and store.read()==after


def test_same_fingerprint_with_restrictions_never_gains_unrestricted_access(tmp_path,key):
    store=access_agent.Store(tmp_path);store.directory.mkdir(mode=0o700)
    original=('restrict,command="echo limited" '+key['public_line']+' original-comment\n').encode()
    store.path.write_bytes(original);store.path.chmod(0o600)
    assert store.apply('a'*32,key['public_line'],access_agent.digest(original))['state']=='already_listed_restricted'
    assert store.read()==original


def test_confirmation_conflict_and_rollback_conflict_do_not_overwrite_changes(tmp_path,key):
    store=access_agent.Store(tmp_path);store.directory.mkdir(mode=0o700)
    original=b'# original\n';store.path.write_bytes(original)
    assert store.apply('a'*32,key['public_line'],access_agent.digest(b''))['state']=='changed_requires_confirmation'
    assert store.read()==original
    assert store.apply('b'*32,key['public_line'],access_agent.digest(original))['state']=='applied'
    with store.path.open('ab') as stream: stream.write(b'# concurrently added\n')
    after=store.read()
    assert store.rollback('b'*32)['state']=='rollback_requires_review'
    assert store.read()==after


@pytest.mark.parametrize('unsafe',['directory_link','file_link','world_writable','fifo'])
def test_unsafe_authorization_paths_refuse_without_changing_sentinel(tmp_path,key,unsafe):
    sentinel=tmp_path/'sentinel';sentinel.write_text('keep')
    home=tmp_path/'home';home.mkdir(mode=0o700);store=access_agent.Store(home)
    if unsafe=='directory_link': store.directory.symlink_to(tmp_path)
    else:
        store.directory.mkdir(mode=0o700)
        if unsafe=='file_link': store.path.symlink_to(sentinel)
        elif unsafe=='fifo': os.mkfifo(store.path)
        else: store.path.write_text('');store.path.chmod(0o666)
    with pytest.raises((ValueError,OSError)): store.apply('a'*32,key['public_line'],access_agent.digest(b''))
    assert sentinel.read_text()=='keep'


def test_interruption_after_append_is_reconciled_without_appending_twice(tmp_path,key,monkeypatch):
    store=access_agent.Store(tmp_path);original=store.journal
    def interrupted(operation,data=None):
        if data and data['state']=='applied': raise ConnectionError('simulated interrupted acknowledgement')
        return original(operation,data)
    monkeypatch.setattr(store,'journal',interrupted)
    with pytest.raises(ConnectionError): store.apply('a'*32,key['public_line'],access_agent.digest(b''))
    assert store.status('a'*32)['state']=='applied'
    assert store.apply('a'*32,key['public_line'],access_agent.digest(b''))['state']=='applied'
    assert store.read().count(key['public_line'].encode())==1


def test_public_file_with_multiple_keys_is_rejected_before_any_connection(tmp_path,key):
    path=Path(key['path']);path.write_text(key['public_line']+'\n'+key['public_line']+'\n')
    with pytest.raises(ValueError,match='exactly one'): access_preview.public_key(path)


def test_frozen_include_closure_keeps_rules_and_detects_changed_inputs(tmp_path):
    source=tmp_path/'config';child=tmp_path/'included.conf';frozen=tmp_path/'frozen';frozen.mkdir()
    child.write_text('Host chosen\n ProxyJump gateway\n')
    source.write_text(f'Include "{child}"\nHost *\n User fixture\n')
    copied,before=ssh_discovery.inspected_configuration(source,frozen)
    child.write_text('Host chosen\n ProxyCommand touch NEVER\n')
    assert 'ProxyJump gateway' in ''.join(path.read_text() for path in frozen.iterdir())
    assert str(child) not in Path(copied).read_text()
    with pytest.raises(ValueError): ssh_discovery.inspected_configuration(source)
    child.write_text('Host chosen\n ProxyJump another_gateway\n')
    assert ssh_discovery.inspected_configuration(source)!=before


@pytest.mark.parametrize('ancestor,expected',[('sshd','openssh'),('sshd-session','openssh'),('tailscaled','tailscale_ssh_policy'),('unknown','unknown')])
def test_login_policy_detection_never_infers_authorized_keys_from_tailscale_ip(monkeypatch,ancestor,expected):
    def text(path,*args,**kwargs):
        if path.name=='comm': return ancestor+'\n'
        if path.name=='status': return 'PPid:\t1\n'
        raise AssertionError(path)
    monkeypatch.setattr(Path,'read_text',text)
    assert access_agent.login_mode()==expected


def test_channel_cleanup_reaps_an_already_exited_leader_and_is_idempotent():
    import sys,time
    from access_transport import Channel
    channel=Channel([sys.executable,'-c','pass'],os.environ.copy(),1)
    time.sleep(.1)
    channel.close();channel.close()
    assert channel.process.returncode==0


@pytest.mark.parametrize('retain',['cancel','keep','collision','unsafe_directory'])
def test_generated_key_is_temporary_until_confirmation_and_never_overwrites(tmp_path,monkeypatch,retain):
    home=tmp_path/'home';home.mkdir(mode=0o700)
    host=ssh_discovery.profile('fixture',tmp_path/'config')
    real_run=subprocess.run
    def fixture_keygen(argv,**kwargs):
        assert '-N' not in argv and argv[:4]==['/usr/bin/ssh-keygen','-q','-t','ed25519']
        return real_run(argv+['-N',''],**kwargs)
    monkeypatch.setattr(subprocess,'run',fixture_keygen)
    # public_key invokes ssh-keygen -l too; allow those read-only validations.
    def command(argv,**kwargs):
        return fixture_keygen(argv,**kwargs) if '-t' in argv else real_run(argv,**kwargs)
    monkeypatch.setattr(subprocess,'run',command)
    with access_setup.prepared_key(host,home=home) as (key,final,commit):
        staged=Path(key['path']).with_suffix('')
        assert staged.exists() and not final.exists()
        if retain=='keep':
            saved=commit(key)
            assert access_preview.public_key(saved)['fingerprint']==key['fingerprint']
            assert final.stat().st_mode&0o777==0o600
        elif retain=='collision':
            final.parent.mkdir(mode=0o700);final.write_text('existing personal file')
            with pytest.raises(FileExistsError): commit(key)
            assert final.read_text()=='existing personal file'
        elif retain=='unsafe_directory':
            other=tmp_path/'other';other.mkdir();final.parent.symlink_to(other)
            with pytest.raises(ValueError,match='Unsafe'): commit(key)
            assert list(other.iterdir())==[]
    assert not staged.exists()
    if retain=='cancel': assert not (home/'.ssh').exists()
    if retain=='keep': assert final.exists() and Path(str(final)+'.pub').exists()


def test_exit_after_final_message_does_not_turn_success_into_uncertain_write(tmp_path):
    import sys
    from access_transport import Channel
    script='import sys; sys.stdin.buffer.readline(); print("PIMUX-ACCESS/1 2\\n{}",flush=True); sys.stdin.buffer.readline()'
    async def check():
        with Channel([sys.executable,'-c',script],os.environ.copy(),2) as channel:
            await channel.send(b'initial\n');assert await channel.receive()=={}
            await channel.send(b'finish\n')
    asyncio.run(check())


def test_partial_append_preserves_evidence_for_coordinated_recovery(tmp_path,key,monkeypatch):
    store=access_agent.Store(tmp_path);store.directory.mkdir(mode=0o700)
    before=b'# preserve\n';store.path.write_bytes(before)
    write=os.write
    def partial(fd,data): return write(fd,data[:20])
    monkeypatch.setattr(os,'write',partial)
    with pytest.raises(OSError,match='Incomplete'): store.apply('a'*32,key['public_line'],access_agent.digest(before))
    assert store.status('a'*32)['state']=='partial_write'
    monkeypatch.setattr(os,'write',write)
    partial=store.read()
    result=store.rollback('a'*32)
    assert result['state']=='rollback_requires_review' and result['observed_state']=='partial_write'
    assert store.read()==partial and store.status('a'*32)['state']=='partial_write'


def test_hardlinked_authorization_file_cannot_modify_another_file(tmp_path,key):
    original=tmp_path/'unrelated';original.write_text('# preserve\n')
    home=tmp_path/'home';home.mkdir(mode=0o700)
    store=access_agent.Store(home);store.directory.mkdir(mode=0o700)
    os.link(original,store.path)
    with pytest.raises(ValueError,match='Unsafe'): store.apply('a'*32,key['public_line'],access_agent.digest(original.read_bytes()))
    assert original.read_text()=='# preserve\n'


@pytest.mark.parametrize('stream',[1,2])
def test_enrollment_channel_flood_and_cancel_are_bounded(stream):
    import sys,time
    from access_transport import Channel
    async def check():
        with Channel([sys.executable,'-c',f'import os,time;os.write({stream},b"x"*200000);time.sleep(20)'],os.environ.copy(),2) as channel:
            with pytest.raises(ValueError,match='output limit'): await channel.receive()
        assert channel.process.poll() is not None
        with Channel([sys.executable,'-c','import time;time.sleep(20)'],os.environ.copy(),2) as channel:
            task=asyncio.create_task(channel.receive());await asyncio.sleep(.02);task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        assert channel.process.poll() is not None
    start=time.monotonic();asyncio.run(check());assert time.monotonic()-start<3


def test_existing_receipt_cannot_be_reassigned_to_a_new_target(tmp_path):
    review=dict(node_id='a'*32,account='fixture',uid=1000,host_key={'fingerprint':'original'},fingerprint='key',configuration_digest='config')
    record={'operation':'a'*32,'review':review,'status':'pending'}
    path=tmp_path/'receipts'/('a'*32+'.json')
    access_setup.save_receipt(path,record)
    access_setup.save_receipt(path,record)
    changed={**record,'review':{**review,'host_key':{'fingerprint':'other'}}}
    with pytest.raises(ValueError,match='target or key changed'): access_setup.save_receipt(path,changed)
    assert json.loads(path.read_text())==record
