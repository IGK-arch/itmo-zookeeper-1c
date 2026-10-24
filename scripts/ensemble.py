"""Run the original zkServer.cmd, inspect roles, stop only registered processes."""
import argparse
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import bootstrap
from bootstrap import ROOT
import psutil

JAVA_HOME = ROOT / 'runtime/jdk-17.0.20.1+1'
REGISTRY = ROOT / 'tmp/server-processes.json'


def java_env():
    env = os.environ.copy()
    env['JAVA_HOME'] = str(JAVA_HOME)
    env['JAVA_TOOL_OPTIONS'] = '-Xms128m -Xmx256m -Dfile.encoding=UTF-8'
    return env


def registry():
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}


def start(number):
    records = registry()
    old = records.get(str(number))
    if old and psutil.pid_exists(old['pid']):
        process = psutil.Process(old['pid'])
        if abs(process.create_time() - old['create_time']) < 0.01:
            return old
    logpath = ROOT / f'logs/zk{number}-server.log'
    with logpath.open('ab') as log:
        proc = subprocess.Popen(['cmd.exe', '/d', '/c', r'bin\zkServer.cmd'],
                                cwd=ROOT / f'servers/zk{number}', env=java_env(),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    record = {'pid': proc.pid, 'create_time': psutil.Process(proc.pid).create_time(),
              'command': r'bin\zkServer.cmd', 'log': str(logpath.relative_to(ROOT))}
    records[str(number)] = record
    REGISTRY.write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(f'START zk{number}: PID {proc.pid}, штатная команда bin\\zkServer.cmd', flush=True)
    return record


def stop(number):
    record = registry().get(str(number))
    if not record or not psutil.pid_exists(record['pid']):
        return
    parent = psutil.Process(record['pid'])
    if abs(parent.create_time() - record['create_time']) >= 0.01:
        raise RuntimeError('PID was reused; refusing to stop another process')
    processes = parent.children(recursive=True) + [parent]
    for proc in reversed(processes):
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(processes, timeout=8)
    print(f'STOP zk{number}: остановлены только процессы этого сервера', flush=True)


def four_letter(number, command='srvr'):
    try:
        with socket.create_connection(('127.0.0.1', 2180 + number), timeout=1.5) as sock:
            sock.sendall(command.encode('ascii'))
            output = []
            while chunk := sock.recv(65536):
                output.append(chunk)
            return b''.join(output).decode('utf-8', errors='replace')
    except OSError as exc:
        return f'UNAVAILABLE: {type(exc).__name__}'


def roles():
    result = {}
    for number in (1, 2, 3):
        raw = four_letter(number)
        role = next((line.split(':', 1)[1].strip() for line in raw.splitlines() if line.startswith('Mode:')), None)
        unavailable = ('offline' if raw.startswith('UNAVAILABLE:')
                       else 'not serving (no quorum)')
        result[str(number)] = {'role': role or unavailable, 'srvr': raw}
    return result


def wait_roles(count=3, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = roles()
        present = [v['role'] for v in result.values()]
        if present.count('leader') == 1 and present.count('follower') == count - 1:
            return result
        time.sleep(0.4)
    raise TimeoutError(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'roles'])
    parser.add_argument('nodes', nargs='*', type=int, choices=[1, 2, 3])
    args = parser.parse_args()
    if args.action == 'roles':
        print(json.dumps(roles(), ensure_ascii=False, indent=2))
    else:
        for node in args.nodes or [1, 2, 3]:
            (start if args.action == 'start' else stop)(node)
        if args.action == 'start':
            print(json.dumps(wait_roles(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
