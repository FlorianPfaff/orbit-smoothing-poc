"""Independent streaming audit of the full external validation archive."""
from pathlib import Path, PurePosixPath
import datetime, gzip, hashlib, json, re, tarfile

ROOT = Path('/mnt/d/orbit-segmented-v4')


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def main():
    assets = ROOT/'validation-evidence-assets04-01'
    publication = ROOT/'publication-validation04-terminal-full-01'
    asset = json.loads((assets/'manifest.json').read_text())
    manifest = json.loads((publication/'manifest.json').read_text())
    archive = Path(asset['archive']['path'])
    assert pin(archive) == asset['archive']
    assert asset['archive_members'] == 2699 and len(manifest['files']) == 2698
    expected = {row['path']: row for row in manifest['files']}
    expected['manifest.json'] = {**pin(publication/'manifest.json'), 'path': 'manifest.json'}
    assert {row['path']: row for row in asset['exact_members']} == expected
    seen, selected = set(), {}
    credential = re.compile(rb'(?:github_pat_[A-Za-z0-9_]{25,}|ghp_[A-Za-z0-9]{25,}|sk-[A-Za-z0-9]{35,}|Authorization:\s*Bearer\s+[A-Za-z0-9._-]{16,})')
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
            assert len(path.parts) > 1 and path.parts[0] == 'validation04-full-evidence'
            name = str(PurePosixPath(*path.parts[1:]))
            assert name not in seen and name in expected
            raw = stream.extractfile(member).read()
            row = expected[name]
            assert len(raw) == member.size == row['bytes']
            assert hashlib.sha256(raw).hexdigest() == row['sha256']
            seen.add(name)
            if name in ('independent-audit.json', 'raw-benchmark/report.json'):
                selected[name] = json.loads(raw)
            if name.endswith(('.json', '.log', '.txt', '.html', '.json.gz')):
                text = gzip.decompress(raw) if name.endswith('.json.gz') else raw
                assert not credential.search(text), 'Credential-shaped content requires manual review'
    assert seen == set(expected)
    assert manifest['benchmark_attempts_executed'] == asset['benchmark_attempts_executed'] == 0
    assert manifest['release_ready'] is asset['release_ready'] is False
    audit = selected['independent-audit.json']
    assert audit['consistency_passed'] is True and audit['benchmark_attempts_executed'] == 0 and audit['release_ready'] is False
    receipt = {'schema': 'orbit-poc-validation04-evidence-archive-independent-review-v1', 'status': 'passed',
               'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'archive': pin(archive), 'asset_manifest': pin(assets/'manifest.json'),
               'full_publication_manifest': pin(publication/'manifest.json'), 'members': len(seen),
               'all_member_bytes_hashes_sizes_types_and_paths_verified': True, 'exact_membership_match': True,
               'core_audit_sha256': expected['independent-audit.json']['sha256'],
               'benchmark_attempts_executed': 0, 'release_ready': False, 'array_payloads_remain_external_to_git': True,
               'audit_script': pin(Path(__file__).resolve()),
               'scope': 'Independent streaming verification of all2699 archive members against the frozen full publication manifest. Bounded prebenchmark evidence only; no extraction, modification or scientific fit.'}
    destination = ROOT/'control/validation04-archive-independent-review-01.json'
    with destination.open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True); stream.write('\n')
    print(json.dumps(pin(destination)))


if __name__ == '__main__':
    main()
