"""Compare all output bytes with lab 3, inspect real ZooKeeper pointers and S3 readbacks."""
import csv
import hashlib
import io
import json
import logging

import bootstrap
from bootstrap import ROOT
from coordinator import HOSTS
from storage import BUCKET, EXPECTED_RESULT_SHA, client
from kazoo.client import KazooClient
from test_ensemble import cli_commands

logging.basicConfig(level=logging.ERROR)


def main():
    experiments = json.loads((ROOT / 'evidence/experiments.json').read_text(encoding='utf-8'))[-2:]
    assert [row['fencing'] for row in experiments] == [False, True]
    reference = (ROOT / 'results/lab3-reference-skills_2.csv').read_bytes()
    assert hashlib.sha256(reference).hexdigest() == EXPECTED_RESULT_SHA
    expected = {(r['skill_1'], r['skill_2']): int(r['count'])
                for r in csv.DictReader(io.StringIO(reference.decode()))}
    zk = KazooClient(hosts=HOSTS, timeout=10)
    zk.start(timeout=10)
    checks = []
    try:
        for experiment in experiments:
            run = experiment['run']
            mode = 'FENCING=1' if experiment['fencing'] else 'FENCING=0'
            print('\n' + mode, '|', run, flush=True)
            for name in ('A', 'B'):
                path = ROOT / f'results/{run}-{name}-skills_2.csv'
                data = path.read_bytes()
                actual = {(r['skill_1'], r['skill_2']): int(r['count'])
                          for r in csv.DictReader(io.StringIO(data.decode()))}
                assert data == reference and actual == expected
                assert len(actual) == 28430 and sum(actual.values()) == 214983
                checks.append({'run': run, 'coordinator': name, 'same_bytes_as_lab3': True,
                               'same_all_counts_as_lab3': True, 'unique_pairs': len(actual),
                               'pair_occurrences': sum(actual.values()), 'bytes': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()})
                print(f'{name}: все 28430 пар и их частоты совпали; сумма частот 214983', flush=True)
            raw, stat = zk.get(experiment['zk_root'] + '/result')
            pointer = json.loads(raw)
            readback = client().get_object(Bucket=BUCKET, Key=pointer['key'])['Body'].read()
            assert readback == reference
            assert stat.version == experiment['pointer_version'] and pointer == experiment['pointer']
            print(f"Указатель: dataVersion={stat.version}, coordinator={pointer['coordinator']}, epoch={pointer['epoch']}", flush=True)
            print('S3 GET: все байты совпали с ДЗ 3', flush=True)
            suffix = 'fenced' if experiment['fencing'] else 'unsafe'
            cli_commands([f"get -s {experiment['zk_root']}/result", f"get -s {experiment['zk_root']}/epoch"],
                         f'zkCli-pointer-{suffix}.txt')
            (ROOT / f'evidence/pointer-{suffix}.json').write_text(
                json.dumps({'path': experiment['zk_root'] + '/result', 'dataVersion': stat.version,
                            'pointer': pointer}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('\nSHA-256 всех четырёх файлов:', flush=True)
        print(EXPECTED_RESULT_SHA, flush=True)
        print('PASS: побайтовое сравнение, все частоты, указатели ZooKeeper и S3', flush=True)
        result = {'reference_repository': 'https://github.com/IGK-arch/itmo-mapreduce-1c',
                  'reference_commit': 'b3e6ac9', 'checks': checks, 'passed': True}
        (ROOT / 'evidence/full-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        zk.stop()
        zk.close()


if __name__ == '__main__':
    main()
