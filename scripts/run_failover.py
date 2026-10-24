"""Suspend a real coordinator process, wait for standby completion, then resume it."""
import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import bootstrap
from bootstrap import ROOT
import psutil
from kazoo.client import KazooClient
from coordinator import HOSTS
from storage import BUCKET, EXPECTED_RESULT_SHA, client

logging.basicConfig(level=logging.ERROR)


def events(run, name):
    path = ROOT / f'logs/{run}-{name}.jsonl'
    if not path.exists():
        return []
    output = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            output.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # The writer may currently be appending the last line.
    return output


def wait_event(run, name, predicate, proc, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = next((row for row in events(run, name) if predicate(row)), None)
        if found:
            return found
        if proc.poll() is not None:
            raise RuntimeError(f'{name} exited with {proc.returncode} before the expected event')
        time.sleep(0.05)
    raise TimeoutError(f'Expected event missing for {run}/{name}')


def experiment(fencing):
    run = ('fenced-' if fencing else 'unsafe-') + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    root = '/lab4/' + run
    zk = KazooClient(hosts=HOSTS, timeout=10)
    zk.start(timeout=10)
    zk.ensure_path(root)
    for name, value in [('epoch', b'0'), ('result', b''), ('checkpoint', b'')]:
        zk.create(root + '/' + name, value)
    env = os.environ.copy()
    env.update(FENCING=str(int(fencing)), PYTHONUTF8='1')
    processes, streams = {}, []
    paused = False
    worker_pid = None

    def launch(name):
        stream = (ROOT / f'logs/{run}-{name}-stdout.log').open('wb')
        streams.append(stream)
        command = [sys.executable, '-u', str(ROOT / 'scripts/run_coordinator.py'), '--run', run, '--name', name]
        proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        processes[name] = proc
        print(f'START {name}: PID={proc.pid}, FENCING={int(fencing)}, session_timeout=10 s', flush=True)
        return proc

    try:
        print('\nRUN', run, flush=True)
        a = launch('A')
        first = wait_event(run, 'A', lambda x: x['event'] == 'checkpoint' and x['rows'] >= 10000, a)
        print(f"A: чекпоинт {first['rows']} строк", flush=True)
        b = launch('B')
        wait_event(run, 'B', lambda x: x['event'] == 'waiting', b)
        checkpoint = wait_event(run, 'A', lambda x: x['event'] == 'checkpoint' and x['rows'] >= 20000, a)
        worker_pid = checkpoint['pid']  # Windows venv/python.exe may be a launcher with a real child process.
        worker = psutil.Process(worker_pid)
        assert worker_pid == a.pid or worker in psutil.Process(a.pid).children(recursive=True)
        requested_ns = time.perf_counter_ns()
        worker.suspend()
        suspended_ns = time.perf_counter_ns()
        paused = True
        pause_utc = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        print(f"SUSPEND A: {pause_utc}, PID расчёта={worker_pid}, последний чекпоинт={checkpoint['rows']} строк", flush=True)
        leader = wait_event(run, 'B', lambda x: x['event'] == 'leader', b, timeout=45)
        elapsed = (leader['monotonic_ns'] - suspended_ns) / 1e9
        print(f"B стал лидером: epoch={leader['epoch']}; смена лидера за {elapsed:.3f} с", flush=True)
        restore = wait_event(run, 'B', lambda x: x['event'] == 'restored', b)
        assert restore['rows'] == checkpoint['rows'] and restore['rows'] < 229388
        print(f"B восстановил {restore['rows']} строк и {restore['unique_pairs']} пар из чекпоинта", flush=True)
        publication_b = wait_event(run, 'B', lambda x: x['event'] == 'published', b)
        assert b.wait(timeout=15) == 0
        print(f"B: записал результат, version={publication_b['pointer_version']}, SHA-256 совпал с ДЗ 3", flush=True)
        while (time.perf_counter_ns() - suspended_ns) / 1e9 < 40:
            time.sleep(0.25)
        assert not any(e['monotonic_ns'] > suspended_ns for e in events(run, 'A')), 'A kept running while supposedly suspended'
        resumed_ns = time.perf_counter_ns()
        worker.resume()
        paused = False
        pause_seconds = (resumed_ns - suspended_ns) / 1e9
        print(f'RESUME A: процесс был приостановлен {pause_seconds:.3f} с', flush=True)
        if a.wait(timeout=120) != 0:
            raise RuntimeError('Resumed A failed; see its stdout log')
        payload, stat = zk.get(root + '/result')
        pointer = json.loads(payload)
        combined = events(run, 'A') + events(run, 'B')
        accepted = [e for e in combined if e['event'] == 'published']
        rejected = [e for e in combined if e['event'] == 'rejected']
        computed = [e for e in combined if e['event'] == 'computed']
        for event in events(run, 'A'):
            if event['event'] in ('published', 'rejected'):
                print('A:', event['message'], '|', {k: event[k] for k in ('epoch', 'pointer_version', 'exception') if k in event}, flush=True)
        assert len(computed) == 2
        assert all(e['sha256'] == EXPECTED_RESULT_SHA for e in computed)
        assert len(accepted) == (1 if fencing else 2)
        assert len(rejected) == int(fencing)
        assert pointer['coordinator'] == ('B' if fencing else 'A')
        assert stat.version == (1 if fencing else 2)
        for name in ('A', 'B'):
            data = (ROOT / f'results/{run}-{name}-skills_2.csv').read_bytes()
            assert hashlib.sha256(data).hexdigest() == EXPECTED_RESULT_SHA
        body = client().get_object(Bucket=BUCKET, Key=pointer['key'])['Body'].read()
        assert hashlib.sha256(body).hexdigest() == EXPECTED_RESULT_SHA
        result = {'run': run, 'fencing': fencing, 'zk_root': root, 'pause_time_utc': pause_utc,
                  'suspend_requested_ns': requested_ns, 'suspended_ns': suspended_ns,
                  'suspended_worker_pid': worker_pid, 'launcher_pid': a.pid,
                  'leader_B_ns': leader['monotonic_ns'], 'resumed_ns': resumed_ns,
                  'failover_seconds': elapsed, 'pause_seconds': pause_seconds,
                  'restored_rows': restore['rows'], 'restored_unique_pairs': restore['unique_pairs'],
                  'accepted_publications': len(accepted), 'rejected_publications': len(rejected),
                  'pointer_version': stat.version, 'pointer': pointer,
                  'computed': [{k: e[k] for k in ('coordinator', 'epoch', 'rows', 'selected', 'emissions', 'unique_pairs', 'sha256')} for e in computed],
                  's3_readback_matches_lab3': True,
                  'session_timeout_ms': 10000, 'batch_delay_seconds': 0.03}
        (ROOT / f'evidence/{run}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest_path = ROOT / 'evidence/experiments.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
        manifest.append(result)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"RESULT: принятых записей={len(accepted)}, отклонённых={len(rejected)}, pointer.version={stat.version}, owner={pointer['coordinator']}", flush=True)
        print('Контроль: 229388 строк; 18164 вакансии 1С; 214983 вхождения пар; 28430 уникальных пар', flush=True)
        print('SHA-256:', EXPECTED_RESULT_SHA, flush=True)
        print('PASS', run, flush=True)
        return result
    finally:
        if paused:
            psutil.Process(worker_pid).resume()
        for proc in processes.values():
            if proc.poll() is None:
                for child in psutil.Process(proc.pid).children(recursive=True):
                    child.terminate()
                proc.terminate()
                proc.wait(timeout=10)
        for stream in streams:
            stream.close()
        zk.stop()
        zk.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fencing', type=int, choices=[0, 1], required=True)
    args = parser.parse_args()
    experiment(bool(args.fencing))
