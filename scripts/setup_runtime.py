"""Download verified official archives and create three independent ZooKeeper copies."""
import concurrent.futures
import hashlib
import json
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA_URL = ('https://github.com/adoptium/temurin17-binaries/releases/download/'
            'jdk-17.0.20.1%2B1/OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip')
JAVA_SHA256 = 'e53a79c3c3d86865bd7e787903884331068e71321714ffd44f145785affc7cb0'
ZK_URL = 'https://archive.apache.org/dist/zookeeper/zookeeper-3.9.6/apache-zookeeper-3.9.6-bin.tar.gz'
ZK_SHA512 = 'e999626df06de30dc8bb53bb51da9bb786b1658406adafc6b92f104d72ca25e869f70a57c83a726f8b9558cc0fb519fc20f201aa5d6da09884bc4be5fe6dd3b0'


def download(url, path, algorithm, expected):
    if not path.exists():
        print('DOWNLOAD', url, flush=True)
        urllib.request.urlretrieve(url, path)
    digest = hashlib.file_digest(path.open('rb'), algorithm).hexdigest()
    if digest != expected:
        raise ValueError(f'Checksum mismatch: {path.name}: {digest}')
    return {'url': url, 'file': path.name, 'bytes': path.stat().st_size,
            algorithm: digest, 'verified': True}


def main():
    for name in ('downloads', 'runtime', 'servers', 'tmp', 'logs', 'results',
                 'evidence', 'evidence/screenshots', 'output/pdf'):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    jobs = [(JAVA_URL, ROOT / 'downloads/java17.zip', 'sha256', JAVA_SHA256),
            (ZK_URL, ROOT / 'downloads/zookeeper.tar.gz', 'sha512', ZK_SHA512)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        metadata = list(pool.map(lambda job: download(*job), jobs))
    print(json.dumps(metadata, indent=2), flush=True)
    (ROOT / 'evidence/downloads.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    java = ROOT / 'runtime/jdk-17.0.20.1+1'
    if not java.exists():
        with zipfile.ZipFile(jobs[0][1]) as archive:
            archive.extractall(ROOT / 'runtime')
    base = ROOT / 'runtime/apache-zookeeper-3.9.6-bin'
    if not base.exists():
        with tarfile.open(jobs[1][1]) as archive:
            archive.extractall(ROOT / 'runtime', filter='data')
    participants = '\n'.join(f'server.{i}=127.0.0.1:{2887+i}:{3887+i}' for i in (1, 2, 3))
    for i in (1, 2, 3):
        target = ROOT / f'servers/zk{i}'
        shutil.copytree(base, target, dirs_exist_ok=True)
        data = target / 'data'
        data.mkdir(exist_ok=True)
        (data / 'myid').write_text(f'{i}\n', encoding='ascii')
        if not (data / 'version-2').exists():
            (data / 'initialize').touch()
        cfg = (f'tickTime=2000\ninitLimit=10\nsyncLimit=5\ndataDir=../zk{i}/data\n'
               f'clientPort={2180+i}\nclientPortAddress=127.0.0.1\n'
               f'standaloneEnabled=false\nminSessionTimeout=10000\nmaxSessionTimeout=10000\n'
               f'admin.serverPort={8080+i}\nadmin.serverAddress=127.0.0.1\n'
               f'4lw.commands.whitelist=ruok,srvr,mntr,stat,cons,isro\n{participants}\n')
        (target / 'conf/zoo.cfg').write_text(cfg, encoding='ascii')
        print(f'CONFIG zk{i}: client={2180+i}, quorum={2887+i}, election={3887+i}, admin={8080+i}', flush=True)


if __name__ == '__main__':
    main()
