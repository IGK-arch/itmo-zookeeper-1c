"""S3 configuration shared by the two independent coordinator processes."""
import json
import os
from pathlib import Path
import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
BUCKET = 'hh-lake'
INPUT_KEY = 'raw/it_vacancies_2024.csv'
EXPECTED_INPUT_SHA = '303db922b541e4440906f5a7e8be32fb55e8808f950ffddb8c272f1548212a65'
EXPECTED_RESULT_SHA = '395e69c74e4515b36b765932f41aef0c5767d04ce67cc7646068a535bbc47b15'


def client():
    access, secret = os.environ.get('RUSTFS_ACCESS_KEY'), os.environ.get('RUSTFS_SECRET_KEY')
    if not (access and secret):
        path = ROOT.parent / 'lab/.credentials.json'
        if not path.is_file():
            raise RuntimeError('Set RUSTFS_ACCESS_KEY and RUSTFS_SECRET_KEY')
        local = json.loads(path.read_text(encoding='utf-8'))
        access, secret = local['access'], local['secret']
    return boto3.client('s3', endpoint_url=os.environ.get('RUSTFS_ENDPOINT_URL', 'http://127.0.0.1:9000'),
                        aws_access_key_id=access, aws_secret_access_key=secret, region_name='us-east-1',
                        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                      retries={'max_attempts': 0}, connect_timeout=3, read_timeout=60,
                                      request_checksum_calculation='when_required',
                                      response_checksum_validation='when_required'))
