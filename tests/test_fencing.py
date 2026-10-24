"""A stale epoch must fail even before the new leader publishes its own result."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bootstrap
from bootstrap import ROOT
import json
import uuid
from kazoo.client import KazooClient
from kazoo.exceptions import BadVersionError
from coordinator import HOSTS, checked_pointer_write

zk = KazooClient(hosts=HOSTS, timeout=10)
zk.start(timeout=10)
root = '/lab4/tests/' + uuid.uuid4().hex
try:
    zk.ensure_path(root)
    zk.create(root + '/epoch', b'0')
    zk.create(root + '/result', b'')
    a_token = zk.set(root + '/epoch', b'1', version=0).version
    b_token = zk.set(root + '/epoch', b'2', version=a_token).version
    failures = 0
    for position in ('before_B_publication', 'after_B_publication'):
        try:
            checked_pointer_write(zk, root + '/epoch', a_token, root + '/result', b'A')
        except BadVersionError:
            failures += 1
        else:
            raise AssertionError('A stale epoch was accepted')
        if position == 'before_B_publication':
            data, stat = zk.get(root + '/result')
            assert data == b'' and stat.version == 0
            checked_pointer_write(zk, root + '/epoch', b_token, root + '/result', b'B')
    data, stat = zk.get(root + '/result')
    assert data == b'B' and stat.version == 1 and failures == 2
    result = {'stale_rejected_before_B_publication': True, 'stale_rejected_after_B_publication': True,
              'receiver_value': data.decode(), 'receiver_version': stat.version,
              'actual_server_exception': 'BadVersionError'}
    (ROOT / 'evidence/fencing-boundary-test.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
finally:
    zk.delete(root, recursive=True)
    zk.stop()
    zk.close()
