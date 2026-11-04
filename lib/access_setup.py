# pimux-managed: separate explicit confirmation workflow; never called by discovery.
import asyncio
import contextlib
import stat
import tempfile
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid

from access_preview import candidates, public_key
from access_identity import identity
import access_identity
from access_transport import Channel, accepted_public_key, configuration_digest, connection, terminal_state, verified_host_key
import hosts
from ssh_discovery import discover


def request(operation, key):
    code = Path(__file__).with_name('access_agent.py').read_bytes()
    data = {'version':1, 'operation':operation, 'key':key['public_line']}
    return str(len(code)).encode() + b'\n' + code + json.dumps(data).encode() + b'\n'


def command(**data): return json.dumps(data).encode() + b'\n'


def verified_result(result, key, review):
    return {**result, '_verified_identity': (key, review)}


def validate_review(reply, operation, key, host, host_key):
    if reply.get('type') != 'review': raise ValueError('Missing enrollment review')
    review = reply.get('review')
    fields = {'version','operation','account','uid','hostname','node_id','mode','fingerprint','file_digest','present','restricted','token'}
    if not isinstance(review, dict) or set(review) != fields: raise ValueError('Invalid review fields')
    if (type(review['version']) is not int or review['version'] != 1 or review['operation'] != operation
            or review['fingerprint'] != key['fingerprint'] or type(review['uid']) is not int or not 0 <= review['uid'] <= 2**32
            or not hosts.literal(review['account'],128) or not review['account'] or not hosts.literal(review['hostname'],255)
            or type(review['present']) is not bool or type(review['restricted']) is not bool
            or review['mode'] not in {'openssh','tailscale_ssh_policy','unknown'}): raise ValueError('Invalid review identity')
    for name, length in [('node_id',32),('file_digest',64),('token',64)]:
        if not isinstance(review[name],str) or not re.fullmatch('[a-f0-9]{'+str(length)+'}',review[name]): raise ValueError('Invalid review digest')
    if host.get('node_id') is not None and host['node_id'] != review['node_id']: raise ValueError('Server identity mismatch')
    return {**review, 'host_id':host['host_id'], 'host_key':host_key}


async def verify(host, key, review, tty=None):
    nonce = uuid.uuid4().hex
    code = Path(__file__).with_name('host_snapshot.py').read_bytes()
    data = {'version':1, 'request_id':nonce, 'host_id':host['host_id'], 'socket':host['socket']}
    payload = str(len(code)).encode() + b'\n' + code + json.dumps(data).encode()
    with connection(host, tty=tty, key_only=identity(key)) as (argv, env, root):
        status, output, _ = await hosts.exchange(argv,payload,120 if tty else host['timeout'],env)
        if status: return False
        snapshot = hosts.decode_snapshot(output,host,nonce)
        return (snapshot['node_id'] == review['node_id'] and snapshot['account'] == {'name':review['account'],'uid':review['uid']}
                and verified_host_key(root) == review['host_key'] and accepted_public_key(root,key['fingerprint']))


def save_receipt(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.stat().st_mode & 0o077: raise ValueError('Unsafe local receipt directory')
    if path.exists() or path.is_symlink():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>65536:
            raise ValueError('Unsafe enrollment receipt')
        previous=json.loads(path.read_text())
        fields=('node_id','account','uid','host_key','fingerprint','configuration_digest')
        if previous['operation']!=data['operation'] or any(previous['review'][name]!=data['review'][name] for name in fields):
            raise ValueError('Pending authorization target or key changed')
        # The remote read has established not_started, and this invocation has
        # obtained a fresh confirmation. Reuse its receipt, not a blind append.
        descriptor,temporary=tempfile.mkstemp(prefix='.receipt-',dir=path.parent)
        try:
            with os.fdopen(descriptor,'w') as stream:
                json.dump(data,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    else:
        descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'w') as stream:
            json.dump(data,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())


IDENTITY_FIELDS=('node_id','account','uid','host_key','fingerprint','configuration_digest')


def same_operation_identity(review,expected):
    return all(name in review and name in expected and review[name]==expected[name] for name in IDENTITY_FIELDS)


def unresolved(operation,reason,**details):
    return {'status':'outcome_requires_review','changed':None,'operation':operation,'reason':reason,**details}


async def reconcile(host, key, operation, expected):
    # Only read state after an uncertain write. Never send another apply.
    if configuration_digest(host)!=expected['configuration_digest']: raise ValueError('Configuration changed during reconciliation')
    with connection(host,key_only=identity(key)) as (argv,env,root), Channel(argv,env,host['timeout']) as channel:
        await channel.send(request(operation,key))
        reply=await channel.receive()
        review=validate_review(reply,operation,key,host,verified_host_key(root))
        review['configuration_digest']=configuration_digest(host)
        if not same_operation_identity(review,expected):
            raise ValueError('Target changed during reconciliation')
        await channel.send(command(action='cancel'))
        if not accepted_public_key(root,key['fingerprint']): raise ValueError('Selected key not authenticated')
        return reply['operation_state']['state']


async def _enroll(host, key_path, confirm, receipt_root, tty=None, operation=None, retain_key=None, expected_review=None):
    """confirm(review) must obtain this run's exact target/key consent.

    No persistent write occurs before it returns True. No general --yes switch.
    A receipt records uncertainty; retries query state before considering a write.
    """
    key=public_key(key_path)
    before_config=configuration_digest(host)
    operation=operation or uuid.uuid4().hex
    if not re.fullmatch('[a-f0-9]{32}',operation): raise ValueError('Invalid operation ID')
    receipt=Path(receipt_root)/(operation+'.json')
    applied=False; review=None
    try:
        with connection(host,tty=tty) as (argv,env,root), Channel(argv,env,120 if tty else host['timeout']) as channel:
            await channel.send(request(operation,key))
            reply=await channel.receive()
            review=validate_review(reply,operation,key,host,verified_host_key(root))
            review['configuration_digest']=before_config
            if expected_review is not None and not same_operation_identity(review,expected_review):
                await channel.send(command(action='cancel'))
                return unresolved(operation,'original_target_identity_changed',requires_new_confirmation=True)
            state=reply['operation_state']['state']
            if reply['operation_state'].get('fingerprint',key['fingerprint'])!=key['fingerprint']:
                await channel.send(command(action='cancel'))
                return unresolved(operation,'operation_record_key_mismatch')
            if review['mode'] != 'openssh':
                await channel.send(command(action='cancel'))
                if expected_review is not None: return unresolved(operation,'original_target_login_mode_unverified',mode=review['mode'])
                return {'status':'policy_managed_or_unknown_login','mode':review['mode'],'changed':False}
            if state != 'not_started' or review['present']:
                await channel.send(command(action='cancel'))
                if state not in {'not_started','applied','not_applied','rolled_back'}:
                    return unresolved(operation,'operation_has_no_authoritative_terminal_state',operation_state=state)
                okay=await verify(host,key,review,tty)
                if expected_review is not None and not okay: return unresolved(operation,'original_target_key_not_verified',operation_state=state)
                result = {'status':'verified_existing' if okay else 'existing_key_not_verified','changed':False,
                          'restricted':review['restricted'],'operation_state':state,'operation':operation}
                return verified_result(result,key,review) if okay else result
            approved=confirm(review)
            if asyncio.iscoroutine(approved): approved=await approved
            if approved is not True:
                await channel.send(command(action='cancel'))
                return {'status':'cancelled','changed':False}
            if configuration_digest(host) != before_config or public_key(key_path) != key:
                await channel.send(command(action='cancel'))
                return {'status':'changed_requires_confirmation','changed':False}
            if retain_key is not None:
                retained = public_key(retain_key(key))
                if any(retained[name] != key[name] for name in ('algorithm','fingerprint','public_line')):
                    raise ValueError('Generated key changed before retention')
                key, key_path = retained, retained['path']
            save_receipt(receipt,{'operation':operation,'host':host,'key':key,'review':review,'status':'pending'})
            # From this point a channel failure has an uncertain write outcome.
            applied=True
            await channel.send(command(action='apply',token=review['token']))
            result=await channel.receive()
            if result.get('type') != 'result': raise ValueError('Invalid enrollment result')
            if result.get('state') != 'applied':
                await channel.send(command(action='finish'))
                return {'status':result.get('state','invalid_result'),'changed':False,'operation':operation}
            try: okay=await verify(host,key,review,tty)
            except (OSError,ValueError,TimeoutError,ConnectionError): okay=False
            if okay:
                await channel.send(command(action='finish'))
                return verified_result({'status':'installed_and_verified','changed':True,'operation':operation},key,review)
            await channel.send(command(action='rollback'))
            rollback=await channel.receive()
            return unresolved(operation,'key_verification_failed_authorization_may_remain',recovery=rollback.get('state'),
                              observed_state=rollback.get('observed_state'),receipt=str(receipt))
    except (OSError,ValueError,TimeoutError,ConnectionError) as error:
        if not applied: raise
        try:
            state=await reconcile(host,key,operation,review)
            if state=='applied': return verified_result({'status':'installed_and_verified_after_reconnect','changed':True,'operation':operation},key,review)
        except (OSError,ValueError,TimeoutError,ConnectionError): state='unknown'
        return {'status':'outcome_requires_review','operation':operation,'operation_state':state,
                'changed':None,'receipt':str(receipt),'reason':type(error).__name__}


def choose_key(host, explicit=None, home=None):
    if explicit: return public_key(explicit)
    remembered = access_identity.load(host)
    if remembered: return remembered['key']
    found=discover(home=home,config_files=[host['ssh_config']] if 'ssh_config' in host else None)
    keys=candidates(home,extra=found['public_key_paths'])
    if len(keys)==1 and 'match_not_evaluated' not in found['notes']: return keys[0]
    for index,key in enumerate(keys,1): print(f'{index}. {hosts.safe_text(key["path"])} · {key["fingerprint"]}')
    if not keys: return None
    selected=input('Choose the public key number: ').strip()
    if not selected.isdigit() or not 1<=int(selected)<=len(keys): raise ValueError('No public key selected')
    return keys[int(selected)-1]


def pending_operation(root,host,key):
    if not root.exists(): return None
    matches=[]
    for path in root.glob('*.json'):
        if path.is_symlink() or path.stat().st_size>65536: raise ValueError('Unsafe enrollment receipt')
        data=json.loads(path.read_text())
        if data.get('status') not in {'pending','outcome_requires_review','changed_requires_review'}: continue
        if data['host']['host_id'] != host['host_id']: continue
        if data['key']['fingerprint'] != key['fingerprint']:
            raise ValueError('An earlier authorization outcome needs reconciliation with its original public key')
        if data['review']['configuration_digest'] != configuration_digest(host):
            raise ValueError('Configuration changed since a pending authorization; review that receipt before selecting a new target')
        matches.append(data['operation'])
    if len(matches)>1: raise ValueError('Several interrupted operations exist; choose --operation from the local receipts')
    return matches[0] if matches else None


async def enroll(host,key_path,confirm,receipt_root,tty=None,operation=None,retain_key=None):
    key=public_key(key_path);root=Path(receipt_root)
    operation=operation or pending_operation(root,host,key) or uuid.uuid4().hex
    if not re.fullmatch('[a-f0-9]{32}',operation): raise ValueError('Invalid operation ID')
    receipt=root/(operation+'.json');previous=None
    if receipt.exists():
        if receipt.is_symlink() or receipt.stat().st_size>65536: raise ValueError('Unsafe enrollment receipt')
        previous=json.loads(receipt.read_text())
        if (previous['operation']!=operation or previous['review']['configuration_digest']!=configuration_digest(host)
                or previous['key']['fingerprint']!=key['fingerprint']):
            return unresolved(operation,'original_configuration_or_public_key_changed',requires_new_confirmation=True)
    try:
        result=await _enroll(host,key_path,confirm,receipt_root,tty,operation,retain_key,
                             previous['review'] if previous else None)
    except (OSError,ValueError,TimeoutError,ConnectionError):
        if previous is None: raise
        return unresolved(operation,'original_target_could_not_be_verified')
    resolved=result['status'] in {'verified_existing','installed_and_verified','installed_and_verified_after_reconnect'}
    verified_identity = result.pop('_verified_identity', None)
    # A failed fast path must never retire the original pending operation.
    # Keep its exact bytes and binding until the original target is verified.
    if previous is not None and not resolved:
        if result['status']!='outcome_requires_review':
            return unresolved(operation,'original_operation_unresolved',last_attempt=result['status'])
        return result
    if receipt.exists():
        data=json.loads(receipt.read_text())
        if previous is not None and not same_operation_identity(data['review'],previous['review']):
            return unresolved(operation,'receipt_identity_changed_during_recovery')
        data['status']=result['status'] if resolved else 'outcome_requires_review'
        descriptor,temporary=tempfile.mkstemp(prefix='.receipt-',dir=root)
        try:
            with os.fdopen(descriptor,'w') as stream:
                json.dump(data,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,receipt)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    if verified_identity is not None:
        try:
            access_identity.remember(host,*verified_identity)
            result['identity_saved'] = True
        except (OSError,ValueError,subprocess.TimeoutExpired):
            # Authorization/verification already succeeded. A local preference
            # failure must never claim the remote write failed or repeat it.
            result['identity_saved'] = False
            result['identity_notice'] = 'Verified access, but the local identity choice could not be saved; select and verify again.'
    return result


@contextlib.contextmanager
def prepared_key(host,explicit=None,home=None):
    home=Path.home() if home is None else Path(home)
    selected=choose_key(host,explicit,home)
    if selected is not None:
        yield selected,None,None
        return
    # Reversible staging stays on the home filesystem for no-copy, no-overwrite
    # retention after the exact target and generated fingerprint are confirmed.
    with tempfile.TemporaryDirectory(prefix='.pimux-key-review-',dir=home) as staging:
        proposed=Path(staging)/'key'
        default=home/'.ssh/id_ed25519'
        if not default.exists() and not default.is_symlink() and not Path(str(default)+'.pub').exists(): final=default
        else: final=home/'.ssh'/('pimux_'+host['host_id']+'_'+uuid.uuid4().hex[:8]+'_ed25519')
        print('No existing public key found. Preparing a temporary Ed25519 key for review.')
        print('Choose its passphrase in ssh-keygen; it is retained only after target/key confirmation.')
        subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-a','64','-f',str(proposed)],check=True,timeout=300)
        selected=public_key(Path(str(proposed)+'.pub'))
        def retain(expected):
            final.parent.mkdir(mode=0o700,exist_ok=True)
            info=final.parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:
                raise ValueError('Unsafe key destination directory')
            if public_key(Path(str(proposed)+'.pub'))!=expected: raise ValueError('Staged public key changed')
            info=proposed.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
                raise ValueError('Unsafe staged key')
            os.link(proposed,final,follow_symlinks=False)
            try: os.link(Path(str(proposed)+'.pub'),Path(str(final)+'.pub'),follow_symlinks=False)
            except BaseException:
                final.unlink();raise
            return Path(str(final)+'.pub')
        yield selected,final,retain


async def terminal_answer(prompt):
    # A blocking input() would prevent the event loop from processing SIGTERM
    # while the user reviews permissions. No background input thread is needed.
    print(prompt,end='',flush=True)
    loop=asyncio.get_running_loop();future=loop.create_future();fd=sys.stdin.fileno();data=bytearray()
    def readable():
        if future.done(): return
        try:
            chunk=os.read(fd,1024)
            if not chunk: raise ValueError('Confirmation cancelled')
            data.extend(chunk)
            if len(data)>4096: raise ValueError('Confirmation input limit')
            if b'\n' in data: future.set_result(bytes(data).split(b'\n',1)[0].decode())
        except (OSError,ValueError,UnicodeError) as error: future.set_exception(error)
    loop.add_reader(fd,readable)
    try: return await future
    finally: loop.remove_reader(fd)


def run_wizard(host,key=None,operation=None):
    if not sys.stdin.isatty(): raise ValueError('Enrollment requires an interactive terminal and target/key confirmation')
    tty=os.ttyname(sys.stdin.fileno())
    with terminal_state(tty):
        with prepared_key(host,key) as (selected,destination,retain):
            async def confirm(review):
                for label,value in [('Target',review['account']+'@'+review['hostname']),('Server ID',review['node_id']),
                                    ('Verified host key',review['host_key']['fingerprint']),('Public key',review['fingerprint'])]:
                    print(label+': '+hosts.safe_text(value))
                if destination:
                    print('Retain new key: '+hosts.safe_text(str(destination))+' (private file 0600; passphrase chosen in ssh-keygen).')
                print('Add persistent public-key login for this account under existing SSH policy; preserve other keys. No privilege elevation.')
                return (await terminal_answer('Authorize this exact target and key now? [yes/N] ')).strip().lower()=='yes'
            result=hosts.run_operation(enroll(host,selected['path'],confirm,Path.home()/'.local/state/pimux/enrollment',tty,operation,retain))
            if destination and destination.exists(): result['retained_public_key']=str(destination)+'.pub'
            print(json.dumps(result,ensure_ascii=True,indent=2))
            return 0 if result['status'] in {'installed_and_verified','installed_and_verified_after_reconnect','verified_existing','cancelled'} else 1
