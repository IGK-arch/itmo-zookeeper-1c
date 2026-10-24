"""Checkpointed pair calculation; the final pointer receiver optionally enforces an epoch."""
import argparse
import csv
import hashlib
import io
import itertools
import json
import logging
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from kazoo.client import KazooClient
from kazoo.exceptions import BadVersionError

from pairs import identity_digest, map_reduce_batch, serialize
from storage import (BUCKET, INPUT_KEY, ROOT, EXPECTED_INPUT_SHA,
                     EXPECTED_RESULT_SHA, client)

HOSTS = '127.0.0.1:2181,127.0.0.1:2182,127.0.0.1:2183'


def checked_pointer_write(zk, epoch_path, epoch_version, pointer_path, data):
    """Epoch check and pointer replacement are one atomic ZooKeeper multi request."""
    transaction = zk.transaction()
    transaction.check(epoch_path, version=epoch_version)
    transaction.set_data(pointer_path, data)
    result = transaction.commit()
    for item in result:
        if isinstance(item, Exception):
            raise item  # The real error returned by ZooKeeper, not an invented exception.
    return result[-1]


class HashingStream(io.RawIOBase):
    def __init__(self, body):
        super().__init__()
        self.body, self.digest, self.total = body, hashlib.sha256(), 0

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.body.read(min(len(buffer), 1024 * 1024))
        self.digest.update(data)
        self.total += len(data)
        buffer[:len(data)] = data
        return len(data)


def run(args):
    log = ROOT / f'logs/{args.run}-{args.name}.jsonl'
    textlog = ROOT / f'logs/{args.run}-{args.name}.log'
    fencing = bool(int(os.environ.get('FENCING', '0')))
    root = '/lab4/' + args.run
    s3 = client()
    event_lock = threading.RLock()

    def event(kind, message, **values):
        row = {'time_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
               'monotonic_ns': time.perf_counter_ns(), 'pid': os.getpid(),
               'coordinator': args.name, 'event': kind, 'message': message, **values}
        line = f"{row['time_utc']} [{args.name}] {message}"
        if values:
            line += ' | ' + json.dumps(values, ensure_ascii=False, separators=(',', ':'))
        with event_lock:
            with log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            with textlog.open('a', encoding='utf-8') as stream:
                stream.write(line + '\n')
            print(line, flush=True)

    zk = KazooClient(hosts=HOSTS, timeout=10.0, randomize_hosts=False)
    zk.add_listener(lambda state: event('session', f'Состояние сессии: {state}', state=state))
    zk.start(timeout=15)
    event('started', 'Координатор запущен', fencing=fencing,
          requested_session_timeout_ms=10000, negotiated_session_timeout_ms=zk._session_timeout,
          session_id=hex(zk.client_id[0]))
    lock = zk.Lock(root + '/election', identifier=args.name)
    event('waiting', 'Ожидаю лидерство')
    try:
        if not lock.acquire(timeout=150):
            raise TimeoutError('Leadership acquisition timed out')
        while True:
            old, stat = zk.get(root + '/epoch')
            epoch = int(old) + 1
            try:
                epoch_stat = zk.set(root + '/epoch', str(epoch).encode(), version=stat.version)
                break
            except BadVersionError:
                continue
        token = epoch_stat.version
        event('leader', 'Стал лидером', epoch=epoch, epoch_version=token)
        data, _ = zk.get(root + '/checkpoint')
        counts, identities, cursor, emissions = Counter(), [], 0, 0
        source = s3.head_object(Bucket=BUCKET, Key=INPUT_KEY)
        etag = source['ETag']
        if data:
            pointer = json.loads(data)
            checkpoint_body = s3.get_object(Bucket=BUCKET, Key=pointer['key'])['Body'].read()
            if hashlib.sha256(checkpoint_body).hexdigest() != pointer['sha256']:
                raise RuntimeError('Checkpoint checksum mismatch')
            cp = json.loads(checkpoint_body)
            if cp['input_etag'] != etag:
                raise RuntimeError('Input changed since checkpoint')
            counts.update({(a, b): count for a, b, count in cp['counts']})
            identities, cursor, emissions = cp['identities'], cp['rows'], cp['emissions']
            event('restored', 'Восстановлен чекпоинт', rows=cursor, selected=len(identities),
                  unique_pairs=len(counts), emissions=emissions, checkpoint_epoch=cp['epoch'])
        else:
            event('fresh', 'Начинаю расчёт с первой строки')

        body = s3.get_object(Bucket=BUCKET, Key=INPUT_KEY, IfMatch=etag)['Body']
        raw = HashingStream(body)
        csv.field_size_limit(16 * 1024 * 1024)
        stream = io.TextIOWrapper(io.BufferedReader(raw, buffer_size=1024 * 1024), encoding='utf-8-sig', newline='')
        reader = csv.DictReader(stream)
        for _ in range(cursor):
            next(reader)  # Re-read the CSV prefix to the saved logical record; do not recount it.
        stale_checkpoint = False
        try:
            while batch := list(itertools.islice(reader, 1000)):
                emissions += map_reduce_batch(batch, counts, identities)
                cursor += len(batch)
                if args.batch_delay:
                    time.sleep(args.batch_delay)
                if cursor % 10000 == 0 and not stale_checkpoint:
                    cp = {'rows': cursor, 'counts': [[a, b, count] for (a, b), count in sorted(counts.items())],
                          'identities': identities, 'emissions': emissions, 'input_etag': etag, 'epoch': epoch}
                    payload = json.dumps(cp, ensure_ascii=False, separators=(',', ':')).encode()
                    key = f'lab4/{args.run}/checkpoints/epoch-{epoch}/rows-{cursor}.json'
                    s3.put_object(Bucket=BUCKET, Key=key, Body=payload, ContentType='application/json')
                    pointer = json.dumps({'key': key, 'sha256': hashlib.sha256(payload).hexdigest()}).encode()
                    try:
                        checked_pointer_write(zk, root + '/epoch', token, root + '/checkpoint', pointer)
                        event('checkpoint', 'Чекпоинт сохранён', rows=cursor, selected=len(identities),
                              unique_pairs=len(counts), emissions=emissions)
                    except BadVersionError:
                        stale_checkpoint = True
                        event('stale_checkpoint', 'Более новая эпоха: свой чекпоинт больше не публикую', epoch=epoch)
        finally:
            stream.close()
            body.close()
        if raw.digest.hexdigest() != EXPECTED_INPUT_SHA:
            raise RuntimeError('Input SHA-256 differs from lab 3')
        output = serialize(counts)
        digest = hashlib.sha256(output).hexdigest()
        if (cursor != 229388 or len(identities) != 18164 or emissions != 214983
                or len(counts) != 28430 or digest != EXPECTED_RESULT_SHA):
            raise RuntimeError('Pair result differs from lab 3')
        if identity_digest(identities) != 'ce286c888c97673cdb42b671a9593f3e73181eb6c56f1e16fed6fa9f2bf8fe2a':
            raise RuntimeError('Selected vacancy IDs differ from lab 3')
        path = ROOT / f'results/{args.run}-{args.name}-skills_2.csv'
        path.write_bytes(output)
        key = f'lab4/{args.run}/results/epoch-{epoch}-{args.name}-skills_2.csv'
        s3.put_object(Bucket=BUCKET, Key=key, Body=output, ContentType='text/csv; charset=utf-8')
        pointer = {'coordinator': args.name, 'epoch': epoch, 'key': key,
                   'sha256': digest, 'rows': cursor, 'selected': len(identities),
                   'emissions': emissions, 'unique_pairs': len(counts)}
        event('computed', 'Расчёт совпал с ДЗ 3', **pointer)
        payload = json.dumps(pointer, ensure_ascii=False).encode()
        try:
            if fencing:
                stat = checked_pointer_write(zk, root + '/epoch', token, root + '/result', payload)
            else:
                stat = zk.set(root + '/result', payload)
            event('published', 'записал результат', pointer_version=stat.version, epoch=epoch,
                  sha256=digest, fencing=fencing)
        except BadVersionError as exc:
            event('rejected', 'BadVersionError: запись устаревшего лидера отклонена',
                  exception=type(exc).__name__, epoch=epoch,
                  current_epoch=int(zk.get(root + '/epoch')[0]))
        event('done', 'Работа завершена')
    finally:
        try:
            lock.release()
        finally:
            zk.stop()
            zk.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--name', required=True, choices=['A', 'B'])
    parser.add_argument('--batch-delay', type=float, default=0.03)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    run(arguments)
