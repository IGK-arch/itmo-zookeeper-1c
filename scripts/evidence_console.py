"""Read-only localhost viewer of actual command output; no terminal emulation."""
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bootstrap
from bootstrap import ROOT
from ensemble import roles

PAGES = {
    'quorum': ('Остановка одного и двух серверов', 'python scripts/test_ensemble.py', 'ensemble-commands.txt'),
    'ephemeral': ('Эфемерный узел в zkCli', 'bin\\zkCli.cmd -server 127.0.0.1:2181,127.0.0.1:2182,127.0.0.1:2183', 'ensemble-commands.txt'),
    'unsafe': ('Приостановка лидера: FENCING=0', 'python scripts/run_failover.py --fencing 0', 'failover-unsafe-commands.txt'),
    'fenced': ('Приостановка лидера: FENCING=1', 'python scripts/run_failover.py --fencing 1', 'failover-fenced-commands.txt'),
    'verify': ('Сверка с лабораторной 3', 'python scripts/verify_results.py', 'verification-commands.txt'),
    'unsafe-pointer': ('Указатель результата: FENCING=0', '', 'zkCli-pointer-unsafe.txt'),
    'fenced-pointer': ('Указатель результата: FENCING=1', '', 'zkCli-pointer-fenced.txt'),
    'setup-process': ('Проверка Java, zoo.cfg и myid', 'python scripts/inspect_setup.py', 'setup-inspection.txt'),
}


def output_for(key):
    if key == 'checkpoint-process':
        experiment = json.loads((ROOT / 'evidence/experiments.json').read_text(encoding='utf-8'))[-2]
        relative = f'logs/{experiment["run"]}-B.log'
        # Verbatim lines from the actual coordinator: connection, election, restore,
        # and two subsequent checkpoints. No generated terminal prompts.
        lines = (ROOT / relative).read_text(encoding='utf-8').splitlines()
        chosen = [line for line in lines if any(text in line for text in
                  ('Координатор запущен', 'Ожидаю лидерство', 'Стал лидером',
                   'Восстановлен чекпоинт', 'Чекпоинт сохранён'))][:6]
        return ('Журнал запасного координатора B', relative, '\n'.join(chosen),
                'Фрагмент журнала запуска: подключение, восстановление и продолжение расчёта')
    if key == 'roles':
        lines = []
        for node, value in roles().items():
            lines.append(f'zk{node} · 127.0.0.1:{2180+int(node)} · команда srvr')
            lines.extend(line for line in value['srvr'].splitlines()
                         if line.startswith(('Zookeeper version:', 'Mode:', 'Node count:', 'Zxid:')))
            lines.append('')
        return 'Роли серверов ZooKeeper', 'srvr → 127.0.0.1:2181 / :2182 / :2183', '\n'.join(lines), 'Живой ответ трёх серверов'
    title, command, filename = PAGES[key]
    path = ROOT / 'evidence' / filename
    output = path.read_text(encoding='utf-8-sig') if path.exists() else 'Команда выполняется; вывод ещё не сохранён.'
    if key == 'quorum':
        output = output.split('\nzkCli, сессия A:')[0].strip()
    elif key == 'ephemeral':
        output = 'zkCli, сессия A:' + output.split('\nzkCli, сессия A:', 1)[1]
    elif key.endswith('-pointer'):
        pointer_file = 'pointer-fenced.json' if key == 'fenced-pointer' else 'pointer-unsafe.json'
        command = 'zkCli: get -s ' + json.loads((ROOT / 'evidence' / pointer_file).read_text(encoding='utf-8'))['path']
        # Keep the complete get -s output, removing Java connection diagnostics only.
        lines = output.splitlines()
        start = next(i for i, line in enumerate(lines) if '] {"coordinator"' in line)
        end = next(i for i in range(start, len(lines)) if lines[i].startswith('numChildren =')) + 1
        output = '\n'.join(lines[start:end])
    return title, command, output.strip(), 'Сохранённый вывод: evidence/' + filename


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        key = self.path.strip('/') or 'roles'
        if key not in PAGES and key not in ('roles', 'checkpoint-process'):
            self.send_error(404)
            return
        title, command, output, source = output_for(key)
        page = '''<!doctype html><html lang="ru"><meta charset="utf-8">
<title>{title} · Лабораторная 4</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#eef1f4;color:#172331;font-family:Segoe UI,Arial,sans-serif}}
main{{width:990px;margin:18px auto;padding:16px 20px;background:#fff;border:1px solid #c8d0da;border-radius:5px}}
.top{{font-size:16px;color:#536072;margin-bottom:8px}}h1{{font-size:25px;font-weight:600;margin:0 0 12px}}
.command{{font:16px/1.4 Consolas,monospace;margin-bottom:11px;overflow-wrap:anywhere}}
pre{{font:18px/1.35 Consolas,monospace;background:#13202d;color:#eef3f8;padding:17px 19px;border:1px solid #34465a;border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}}
footer{{font-size:14px;color:#536072;margin-top:10px;overflow-wrap:anywhere}}</style>
<main><div class="top">Лабораторная работа 4 · ZooKeeper 3.9.6 · Вариант 1: разработчики 1С</div>
<h1>{title}</h1><div class="command">{command}</div><pre>{output}</pre><footer>{source}</footer></main></html>'''
        body = page.format(**{name: html.escape(value) for name, value in
                              dict(title=title, command=command, output=output, source=source).items()}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    print('Read-only evidence console: http://127.0.0.1:8766/roles', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
