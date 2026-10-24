"""Actual server failures, quorum operation and two real zkCli.cmd sessions."""
import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timezone

import bootstrap
from bootstrap import ROOT
from ensemble import java_env, roles, start, stop, wait_roles
from kazoo.client import KazooClient

HOSTS = '127.0.0.1:2181,127.0.0.1:2182,127.0.0.1:2183'
logging.basicConfig(level=logging.ERROR)


def operation(label):
    zk = KazooClient(hosts=HOSTS, timeout=10.0)
    try:
        zk.start(timeout=4)
        zk.ensure_path('/lab4')
        path = '/lab4/quorum-proof'
        if not zk.exists(path):
            zk.create(path, b'initial')
        zk.set_async(path, label.encode()).get(timeout=4)
        data, stat = zk.get_async(path).get(timeout=4)
        return {'available': True, 'readback': data.decode(), 'version': stat.version}
    except Exception as exc:
        return {'available': False, 'exception': type(exc).__name__}
    finally:
        zk.stop()
        zk.close()


def test_quorum():
    stages = []

    def record(label, expected):
        state = {'stage': label, 'time_utc': datetime.now(timezone.utc).isoformat(),
                 'servers': roles(), 'operation': operation(label)}
        stages.append(state)
        print('\n' + label, flush=True)
        for node, value in state['servers'].items():
            print(f"zk{node}: {value['role']}", flush=True)
        print('SET + GET:', json.dumps(state['operation'], ensure_ascii=False), flush=True)
        assert state['operation']['available'] is expected
        return state

    initial = wait_roles()
    followers = [int(node) for node, value in initial.items() if value['role'] == 'follower']
    try:
        record('Три сервера', True)
        stop(followers[0])
        wait_roles(count=2)
        record(f'Остановлен zk{followers[0]}: осталось 2/3', True)
        stop(followers[1])
        time.sleep(5)
        record(f'Остановлены zk{followers[0]}, zk{followers[1]}: осталось 1/3', False)
    finally:
        for number in followers:
            start(number)
        wait_roles()
    record('Оба сервера возвращены: 3/3', True)
    (ROOT / 'evidence/quorum.json').write_text(json.dumps(stages, ensure_ascii=False, indent=2), encoding='utf-8')


def cli():
    return subprocess.Popen(['cmd.exe', '/d', '/c', r'bin\zkCli.cmd', '-server', HOSTS],
                            cwd=ROOT / 'servers/zk1', env=java_env(), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace', bufsize=1,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def cli_commands(commands, filename):
    proc = cli()
    output, _ = proc.communicate('\n'.join(commands + ['quit', '']), timeout=35)
    (ROOT / 'evidence' / filename).write_text(output, encoding='utf-8')
    assert proc.returncode == 0, output[-1500:]
    return output


def test_ephemeral():
    path = '/lab4-ephemeral-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    owner = cli()
    lines = []

    def collect():
        lines.extend(owner.stdout)

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    observer = KazooClient(hosts=HOSTS, timeout=10)
    observer.start(timeout=10)
    try:
        owner.stdin.write(f'create -e {path} session-owner\n')
        owner.stdin.flush()
        deadline = time.monotonic() + 25
        stat = None
        while time.monotonic() < deadline:
            stat = observer.exists(path)
            if stat:
                break
            time.sleep(0.1)
        assert stat and stat.ephemeralOwner
        before = cli_commands([f'get -s {path}'], 'zkCli-observer-before.txt')
        assert 'session-owner' in before
        print('\nzkCli, сессия A:', f'create -e {path} session-owner', flush=True)
        print(f'zkCli, сессия B: get -s {path}', flush=True)
        for line in before.splitlines():
            if any(key in line for key in ('session-owner', 'ephemeralOwner', 'dataVersion', 'dataLength')):
                print(line, flush=True)
        closed_at = time.perf_counter()
        owner.stdin.write('quit\n')
        owner.stdin.flush()
        owner.wait(timeout=15)
        thread.join(timeout=3)
        (ROOT / 'evidence/zkCli-owner.txt').write_text(''.join(lines), encoding='utf-8')
        deadline = time.monotonic() + 12
        while observer.exists(path) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert observer.exists(path) is None
        delay = time.perf_counter() - closed_at
        after = cli_commands([f'get -s {path}'], 'zkCli-observer-after.txt')
        assert 'Node does not exist' in after
        print('zkCli, сессия A: quit (закрытие клиента)', flush=True)
        print('zkCli, сессия B:', next(line for line in after.splitlines() if 'Node does not exist' in line), flush=True)
        result = {'path': path, 'ephemeral_owner': hex(stat.ephemeralOwner), 'present_before': True,
                  'present_after': False, 'checked_after_seconds': delay, 'owner_exit_code': owner.returncode,
                  'close_method': 'zkCli quit: normal client session close'}
        (ROOT / 'evidence/ephemeral.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    finally:
        observer.stop()
        observer.close()
        if owner.poll() is None:
            owner.kill()


if __name__ == '__main__':
    test_quorum()
    test_ephemeral()
    print('\nPASS: кворум и эфемерный узел', flush=True)
