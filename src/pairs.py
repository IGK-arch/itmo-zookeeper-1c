"""The same variant predicate, skill normalization and pair reduction as lab 3."""
import csv
import hashlib
import io
import itertools
import re

PROGRAMMER = re.compile(r'программист|разработчик|developer|programmer', re.I)
ONE_C = re.compile(r'1[сc]', re.I)
BITRIX = re.compile(r'битрикс|bitrix', re.I)
JAVA_DEVELOPER = re.compile(r'java[\s-]+developer', re.I)


def selected(row):
    name = row.get('name', '')
    return bool(row.get('role') == 'Программист, разработчик'
                and ONE_C.search(name) and PROGRAMMER.search(name)
                and not BITRIX.search(name) and not JAVA_DEVELOPER.search(name))


def map_reduce_batch(rows, counts, identities):
    emitted = 0
    for row in rows:
        if not selected(row):
            continue
        identities.append(row['source'] + ':' + row['vacancy_id'])
        skills = sorted({s.strip().lower() for s in row.get('key_skills', '').split(';') if s.strip()})
        pairs = list(itertools.combinations(skills, 2))
        emitted += len(pairs)
        counts.update(pairs)
    return emitted


def serialize(counts):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(['skill_1', 'skill_2', 'count'])
    writer.writerows((a, b, counts[(a, b)]) for a, b in sorted(counts))
    return stream.getvalue().encode('utf-8')


def identity_digest(identities):
    if len(identities) != len(set(identities)):
        raise RuntimeError('Duplicate vacancy identities')
    return hashlib.sha256('\n'.join(sorted(identities)).encode()).hexdigest()
