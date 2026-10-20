#!/usr/bin/env python3
"""Prepare a thin candidate06/profiles03 packet from terminal actual evidence.

Readiness-only control: this script does not run fits, checkers, tests, Git or
publication. Run only after terminal run/check receipts and the actual outcome
audit exist. Failed/missing attempts and failed checks remain reporter outcomes;
no requirement here converts them into success. The unchanged pinned reporter
sets release_authority, whole_fit_convergence_claim and speedup_claim to false.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

B = Path('/home/emper/orbit-nuisance-warmstarts')
C = B/'source-candidate06'
REPORT_SHA256 = '849c022025e20ac461f521d1cd50436eb68926498b0aa7a40fd2dcfe1558cfd0'
READY_SHA256 = 'fd4887f94bb336553c4684d62954583f6f50c01e516c9058c5d75a2285077161'
INVENTORY_SHA256 = 'd26440d3f85ee9e633e451b5dc001a2d8ca8f407e08c8a009731228274746640'
PREVIOUS_PUBLICATION_COMMIT = 'e5d6c58d4e604511a52a4811d0202e15b57cafef'

EVIDENCE = (
    'control/make_profiles03_packet.py',
    'control/candidate06-copy01.json',
    'control/candidate06-ready01/readiness.json',
    'control/candidate06-ready01/source-inventory.json',
    'control/candidate06-ready01/candidate05-to06.diff',
    'control/candidate06-focused01/execution.json',
    'control/candidate06-focused01/tests.xml',
    'control/candidate06-focused01/pytest.log',
    'control/candidate06-focused02/execution.json',
    'control/candidate06-focused02/tests.xml',
    'control/candidate06-focused02/pytest.log',
    'control/cold-origin-diagnosis05/receipt.json',
    'control/cold-origin-diagnosis05/ulp-clarification.json',
    'control/review02/candidate06-controls/independent-review.json',
    'control/review02/candidate06-source/diagnosis-review.json',
    'control/review02/candidate06-source/snapshot.json',
    'control/review02/candidate06-source/tests.xml',
    'control/review02/candidate06-source/tests.log',
    'control/campaign-preservation05/receipt.json',
    'control/build_candidate06.py',
    'control/candidate-build-plan06.json',
    'control/candidate-build-result06.json',
    'control/candidate-build-supervisor06.json',
    'control/candidate-build06.log',
    'control/run_native_tests03.py',
    'native-tests03/freeze.json',
    'control/check_profiles03.py',
    'control/check_profiles03-delta.json',
    'control/check_profiles03.diff',
    'control/profiles03-check-execution-index.json',
    'profiles03/run-result.json',
    'source-candidate06/groops/extension/nuisanceWarmState.h',
    'source-candidate06/groops/extension/native_nuisance_warm.py',
    'source-candidate06/tests/nuisance_warm_clock_origin_fixture.cpp',
    'source-candidate06/tests/test_nuisance_warm_clock_origin.py',
    'source-candidate06/docs/native-nuisance-warm-state.md',
    # These are earlier actual outcomes, never substituted for candidate06.
    'control/candidate-build-result02.json',
    'control/candidate-build02.log',
    'control/candidate-build-result05.json',
    'control/review02/profiles02-outcomes/independent-review.json',
    'control/warm-application-bottleneck05/receipt.json',
    'control/warm-application-bottleneck05/measurements.json',
    'publication-source05/validation/nuisance-warm-starts/candidate05-profiles02/manifest.json',
    'publication-source05/validation/nuisance-warm-starts/candidate05-profiles02/summary.json',
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regular(path):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink() and path.resolve() == path,
            'Missing/nonregular/symlink evidence: ' + str(path))
    require(path.stat().st_size <= 16 * 1024**2, 'Thin evidence limit: ' + str(path))
    return path


def prepare(args):
    output = args.output.absolute()
    require(not output.exists() and not output.is_symlink(), 'Refuse existing packet')
    output = output.resolve()
    protected = [B/'source', C, B/'source-candidate05', B/'profiles03',
                 B/'profiles02', B/'native-tests03', B/'native-tests02',
                 B/'profiles-prepared01', B/'profiles-prepared02', B/'native-source-06',
                 B/'build-06', B/'binaries', B/'control']
    require(not any(output == p or output.is_relative_to(p) or p.is_relative_to(output)
                    for p in protected), 'Packet overlaps protected source/control/attempt tree')
    log = B/'control/report-candidate06-profiles03.log'
    require(not log.exists(), 'Refuse existing report execution log')
    report = regular(C/'scripts/report_nuisance_warm_profiles.py')
    require(sha(report) == REPORT_SHA256, 'Reviewed reporter changed')
    ready = regular(B/'control/candidate06-ready01/readiness.json')
    inventory = regular(B/'control/candidate06-ready01/source-inventory.json')
    require(sha(ready) == READY_SHA256 and sha(inventory) == INVENTORY_SHA256,
            'Candidate06 readiness/source inventory changed')
    freeze = regular(B/'profiles03/freeze.json')
    run = json.loads(regular(B/'profiles03/run-result.json').read_text())
    require(run.get('freeze', {}).get('sha256') == sha(freeze),
            'Terminal run receipt freeze mismatch')
    index = json.loads(regular(B/'control/profiles03-check-execution-index.json').read_text())
    require(index.get('freeze_sha256') == sha(freeze), 'Check execution freeze mismatch')
    native_tests = regular(B/'native-tests03/result.json')
    audit = regular(args.audit)
    reviews = [regular(p) for p in args.review]
    # Actual review paths are explicit, so no receipt is invented or silently
    # inferred from an earlier candidate's source/control/outcome review.
    require(reviews, 'Supply actual candidate06 source/runtime/launch reviews with --review')
    evidence = [regular(B/p) for p in EVIDENCE] + reviews
    for group in ('pulses', 'density', 'pulses-bias-priors'):
        for check in ('inert-full', 'inert-clock', 'warm-source-full',
                      'warm-target-full', 'warm-target-clock'):
            path = B/'profiles03-checks'/f'{group}--{check}.log'
            if path.exists():
                evidence.append(regular(path))
    for suite in ('native', 'correction'):
        for name in ('tests.xml', 'pytest.log', 'supervisor.json', 'result.json'):
            path = B/'native-tests03'/suite/name
            if path.exists():
                evidence.append(regular(path))
    evidence = list(dict.fromkeys(evidence))
    command = ['/usr/bin/taskset', '-c', '4', sys.executable, '-s', '-B', str(report),
               '--freeze', str(freeze), '--checks', str(B/'profiles03-checks'),
               '--native-tests', str(native_tests), '--outcome-audit', str(audit),
               '--output', str(output)]
    for path in evidence:
        command.extend(['--evidence', str(path)])
    pins = {str(p): sha(p) for p in [report, freeze, native_tests, audit, *evidence]}
    return command, pins, log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--review', type=Path, action='append', default=[],
                        help='Actual candidate06 source/runtime/launch review; repeat as needed')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    command, pins, log = prepare(args)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith('ORBIT_POC_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
    environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                       NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1',
                       LD_LIBRARY_PATH=str(B/'toolchain-01/lib'))
    result = subprocess.run(command, cwd=C, env=environment, capture_output=True, text=True)
    changed = [p for p, digest in pins.items() if sha(p) != digest]
    with log.open('x') as stream:
        stream.write(result.stdout + result.stderr)
        stream.write('\n' + json.dumps({'source': 'candidate06/profiles03',
            'previous_publication_commit': PREVIOUS_PUBLICATION_COMMIT,
            'returncode': result.returncode, 'changed_evidence': changed,
            'release_authority': False, 'whole_fit_convergence_claim': False,
            'speedup_claim': False}, sort_keys=True) + '\n')
    print(result.stdout + result.stderr, end='')
    require(not changed, 'Evidence changed during report; preserve packet as invalid: ' + str(changed))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
