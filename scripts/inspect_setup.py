"""Print the actual Java version and settings read from all three server copies."""
import subprocess

import bootstrap
from bootstrap import ROOT
from ensemble import JAVA_HOME, java_env


def main():
    print('JAVA_HOME=' + str(JAVA_HOME), flush=True)
    print('java -version', flush=True)
    version = subprocess.run([str(JAVA_HOME / 'bin/java.exe'), '-version'],
                             env=java_env(), capture_output=True, text=True,
                             encoding='utf-8', errors='replace', check=True)
    for line in (version.stdout + version.stderr).splitlines():
        if not line.startswith('Picked up JAVA_TOOL_OPTIONS:'):
            print(line, flush=True)
    print('\nconf/zoo.cfg и data/myid трёх копий:', flush=True)
    participants = []
    data_dirs = []
    for n in (1, 2, 3):
        server = ROOT / f'servers/zk{n}'
        config = dict(line.split('=', 1) for line in
                      (server / 'conf/zoo.cfg').read_text(encoding='ascii').splitlines()
                      if '=' in line)
        data = (server / config['dataDir']).resolve()
        myid = (data / 'myid').read_text(encoding='ascii').strip()
        print(f'zk{n}: myid={myid}, clientPort={config["clientPort"]}, dataDir={config["dataDir"]}', flush=True)
        assert myid == str(n)
        data_dirs.append(data)
        participants.append([f'server.{i}={config[f"server.{i}"]}' for i in (1, 2, 3)])
    assert len(set(data_dirs)) == 3 and participants[0] == participants[1] == participants[2]
    print('\nОбщий список участников:', flush=True)
    print('\n'.join(participants[0]), flush=True)


if __name__ == '__main__':
    main()
