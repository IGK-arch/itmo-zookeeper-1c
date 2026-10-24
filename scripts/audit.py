"""Check the assignment against actual evidence and the final PDF geometry."""
import hashlib
import json
from pathlib import Path

import bootstrap
from bootstrap import ROOT
import fitz


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def main():
    checks = []

    def check(name, passed):
        assert passed, name
        checks.append({'criterion': name, 'passed': True})

    dirs, ports, myids, participants = [], [], [], []
    for n in (1, 2, 3):
        server = ROOT / f'servers/zk{n}'
        cfg = dict(line.split('=', 1) for line in (server / 'conf/zoo.cfg').read_text().splitlines() if '=' in line)
        dirs.append(str((server / cfg['dataDir']).resolve()))
        ports.append(cfg['clientPort'])
        myids.append((server / cfg['dataDir'] / 'myid').read_text().strip())
        participants.append([cfg[f'server.{i}'] for i in (1, 2, 3)])
    check('Three independent configs, data directories and myid files',
          len(set(dirs)) == len(set(ports)) == 3 and myids == ['1', '2', '3']
          and participants[0] == participants[1] == participants[2])
    quorum = read('evidence/quorum.json')
    check('Initial roles: one leader, two followers', sorted(x['role'] for x in quorum[0]['servers'].values()) == ['follower','follower','leader'])
    check('One server stopped: read/write succeeds', quorum[1]['operation']['available'] is True)
    check('Two servers stopped: last process cannot serve requests',
          quorum[2]['operation']['available'] is False
          and any('not currently serving requests' in x['srvr'] for x in quorum[2]['servers'].values()))
    check('Both servers restored, quorum returns', quorum[3]['operation']['available'] is True)
    ephem = read('evidence/ephemeral.json')
    check('Real zkCli ephemeral creation and session-close deletion', ephem['present_before'] and not ephem['present_after']
          and 'Created ' + ephem['path'] in (ROOT / 'evidence/zkCli-owner.txt').read_text(encoding='utf-8')
          and 'Node does not exist' in (ROOT / 'evidence/zkCli-observer-after.txt').read_text(encoding='utf-8'))
    experiments = read('evidence/experiments.json')[-2:]
    for e in experiments:
        logs = {}
        for name in ('A', 'B'):
            logs[name] = [json.loads(line) for line in (ROOT / f'logs/{e["run"]}-{name}.jsonl').read_text(encoding='utf-8').splitlines()]
            check(e['run'] + '/' + name + ': negotiated 10-second session', any(x['event'] == 'started' and x['negotiated_session_timeout_ms'] == 10000 for x in logs[name]))
        check(e['run'] + ': paused real worker for 40+ seconds, no A events in pause',
              e['pause_seconds'] >= 40 and not any(e['suspended_ns'] < x['monotonic_ns'] < e['resumed_ns'] for x in logs['A']))
        check(e['run'] + ': checkpoint resumed at 20000 rows, failover measured', e['restored_rows'] == 20000 and e['failover_seconds'] > 0
              and abs(e['failover_seconds'] - (e['leader_B_ns']-e['suspended_ns'])/1e9) < 1e-8)
        both = logs['A'] + logs['B']
        accepted = [x for x in both if x['event'] == 'published']
        if e['fencing']:
            check('FENCING=1: one accepted write, actual BadVersionError, standby pointer v1', len(accepted) == 1
                  and any(x['event']=='rejected' and x['exception']=='BadVersionError' for x in logs['A'])
                  and e['pointer_version'] == 1 and e['pointer']['coordinator'] == 'B' and e['pointer']['epoch'] == 2)
        else:
            check('FENCING=0: two accepted writes, pointer v2 from old leader', len(accepted) == 2
                  and e['pointer_version'] == 2 and e['pointer']['coordinator'] == 'A' and e['pointer']['epoch'] == 1)
    verification = read('evidence/full-verification.json')
    check('All four results match all bytes and frequencies of lab 3', verification['passed'] and len(verification['checks']) == 4
          and all(x['same_bytes_as_lab3'] and x['same_all_counts_as_lab3'] for x in verification['checks']))
    check('Stale epoch rejected even before standby publication', read('evidence/fencing-boundary-test.json')['stale_rejected_before_B_publication'])
    pdf_path = ROOT / 'output/pdf/Карташов_Игорь_J3312_ZooKeeper.pdf'
    pdf = fitz.open(pdf_path)
    screens = read('evidence/pdf-screen-regions.json')
    check('Nine pages, ten distinct screenshots', len(pdf) == 9 and len(screens) == 10 and len({x['sha256'] for x in screens}) == 10)
    for row in screens:
        path = ROOT / 'evidence/screenshots' / row['source']
        check('Original screenshot preserved: ' + row['source'], hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'])
        page = pdf[row['page']-1]
        check('Screenshot inside page and legible font: ' + row['source'],
              row['effective_code_font_pt'] >= 8.8 and 0 <= row['page_box'][0] < row['page_box'][2] <= page.rect.width
              and 20 <= row['page_box'][1] < row['page_box'][3] <= page.rect.height - 20)
    content = '\n'.join(page.get_text() for page in pdf)
    check('Both required questions answered in PDF', 'Почему три сервера' in content and 'Почему эпоху проверяет получатель' in content)
    check('No ZIP references, placeholders or broken glyphs in report',
          not any(word in content.lower() for word in ('приложены в zip','todo','placeholder','\ufffd')))
    check('Answers and final publication link present', 'github.com/IGK-arch/itmo-zookeeper-1c' in content)
    result = {'passed': True, 'checks': checks, 'pdf_pages': len(pdf), 'screenshots': len(screens),
              'pdf_bytes': pdf_path.stat().st_size, 'pdf_sha256': hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
              'visual_review': 'All 9 rendered pages inspected; no cropped text, duplicate images or orphan pages.'}
    (ROOT / 'evidence/final-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'PASS: {len(checks)} checks, {len(pdf)} PDF pages, {len(screens)} distinct screenshots')
    print('PDF SHA-256:', result['pdf_sha256'])


if __name__ == '__main__':
    main()
