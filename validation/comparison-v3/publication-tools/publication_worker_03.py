#!/usr/bin/env python3
"""Finite candidate03 transfer/push steps. Never start estimators or the handoff.

--wait-for-bundle polls only the existing remote handoff status, then transfers
and verifies an immutable bundle. --publish is a separate authorized action in
a fresh clone. Existing reports, runtime sources and PR #1 are never rewritten.
"""
from __future__ import annotations

import argparse
import ctypes
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time

VERIFIER_SHA = 'f5508c70b9bfb59b870ca0daab454e53a2ccab71108f012f7109eef68a621804'
if hashlib.sha256(Path(__file__).with_name('completion_handoff_03.py').read_bytes()).hexdigest()!=VERIFIER_SHA:
    raise RuntimeError('Publication verifier differs from the reviewed candidate03 helper')
import completion_handoff_03 as integrity

SOURCE, PROTOCOL, NATIVE = integrity.SOURCE, integrity.PROTOCOL, integrity.NATIVE
HOST = 'gpuserver6000'
BASE = '/home/florianpfaff/codex-runs/orbit-comparison-v3-20261013'
DATA = '/mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff'
REMOTE_BUNDLE = DATA+'/publication/v3'
REMOTE_STATUS = DATA+'/publication/.v3-handoff-03/status.json'
REPOSITORY = 'https://github.com/FlorianPfaff/orbit-smoothing-poc.git'
BRANCH = 'comparison-groops-v3'
GH = '/mnt/c/Program Files/GitHub CLI/gh.exe'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2']
CAMPAIGNS = {'synthetic':('synthetic','primary',1600), 'stress':('synthetic','stress',20),
             'flight':('flight','primary',24), 'flight_ar_reference':('flight','flight_ar_reference',6)}
METADATA = 'validation/comparison-v3/frozen-package-metadata'
README_PENDING_SHA = '11655d2b6989628bf82312e3ba6ac774c617de26f7d5272fc0a0e01772dc4093'
WORKSPACE = Path(__file__).resolve().parents[3]
DEFAULT_REPO = WORKSPACE/'outputs/orbit-smoothing-poc'
DEFAULT_CONTROL = Path(__file__).resolve().parent/'local-publication-03'


def sha(path): return integrity.sha(path)
def canonical(value): return integrity.canonical(value)
def read(path): return integrity.read(path)
def document(root, name): return integrity.json_artifact(root, name)[0]


def command(argv, *, cwd=None, timeout=60, input=None):
    """No shell interpolation; credentials travel only through Git's helper pipe."""
    result = subprocess.run(argv, cwd=cwd, input=input, text=True, capture_output=True,
                            timeout=timeout, env={**os.environ, 'GIT_TERMINAL_PROMPT':'0'})
    if result.returncode:
        # Never include subprocess stdout (Git credential helper can emit secrets).
        raise RuntimeError(f'{Path(argv[0]).name} exited {result.returncode}: {result.stderr[-2000:]}')
    return result.stdout


class Journal:
    def __init__(self, directory, repo):
        self.directory = directory; self.path = directory/'status.json'
        self.binding = {'repository':REPOSITORY, 'branch':BRANCH, 'local_repo':str(repo),
            'remote_status':REMOTE_STATUS, 'remote_bundle':REMOTE_BUNDLE,
            'source_sha256':SOURCE, 'protocol_hash':PROTOCOL, 'native_sha256':NATIVE}
        self.previous = read(self.path) if self.path.exists() else None
        if self.previous and self.previous.get('binding') != self.binding:
            raise ValueError('Existing worker binding differs; status preserved')
        self.sequence = max([int(p.name.split('-',1)[0]) for p in directory.glob('[0-9]*-*.json')] or [0])

    def record(self, status, phase, **details):
        self.sequence += 1
        result = {'schema_version':1, 'status':status, 'phase':phase, 'binding':self.binding,
            'recorded_at_utc':datetime.now(timezone.utc).isoformat(), 'sequence':self.sequence,
            'worker_sha256':sha(__file__), 'verifier_sha256':sha(integrity.__file__),
            'scientific_superiority_claim':False, 'estimators_launched':False, **details}
        integrity.atomic_json(self.directory/f'{self.sequence:06d}-{status}.json', result)
        integrity.atomic_json(self.path, result)
        return result


@contextmanager
def lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'worker.lock').open('a+') as stream:
        try: fcntl.flock(stream.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another local publication worker holds the lock')
        yield


def rows(root, name):
    return [json.loads(line) for line in integrity.member(root,name).read_text().splitlines() if line.strip()]


def verify_bundle(root):
    """Independent design/row checks supplement the shared byte-level verifier."""
    root=Path(root)
    if root.is_symlink(): raise ValueError('Bundle root cannot be a symlink')
    verified = integrity.verify_bundle(root)
    files = read(root/'publication.json')['files']
    if any(integrity.member(root,name).stat().st_size > 95*1024*1024 for name in files):
        raise ValueError('Publication file exceeds 95 MiB')
    if (root/'publication.json').stat().st_size > 95*1024*1024: raise ValueError('Oversized publication manifest')
    protocol = document(root,'protocol.json')
    if len(protocol['source']['files']) != 89 or canonical(protocol['source']['files']) != SOURCE:
        raise ValueError('Frozen source map does not contain the exact 89-file snapshot')
    metrics = rows(root,'metrics.jsonl'); expected_metrics = set(); calibration_rows = []
    summaries = document(root,'summary.json'); by_key = {}
    for row in metrics:
        key=(row['campaign'],canonical(row['case']),row['method'])
        if key in by_key: raise ValueError('Duplicate compact fit row')
        by_key[key]=row
    for stage in ('synthetic','flight'):
        selection = document(root,f'calibration-{stage}.json')
        fields=('protocol_hash','selections','evidence','calibration_adequate','calibration_disclosures','boundary_diagnostics')
        if (selection.get('complete') is not True or selection.get('stage') != stage
                or selection.get('source_hash') != SOURCE or selection.get('protocol_hash') != PROTOCOL
                or canonical({k:selection[k] for k in fields}) != selection.get('selection_hash')):
            raise ValueError('Calibration selection identity differs')
        frozen = document(root,f'evaluation-input-freeze-{stage}.json')
        if (frozen.get('status') != 'frozen' or frozen.get('stage') != stage
                or frozen.get('protocol_hash') != PROTOCOL or frozen.get('source_hash') != SOURCE
                or frozen.get('native_binary') != protocol['native_binary']
                or frozen.get('selection_hash') != selection['selection_hash']
                or canonical({k:v for k,v in frozen.items() if k!='input_freeze_hash'}) != frozen.get('input_freeze_hash')):
            raise ValueError('Evaluation input freeze differs')
        calibration_rows.extend({'stage':stage,**row} for row in selection['runs'])
        for campaign,(campaign_stage,kind,count) in CAMPAIGNS.items():
            if campaign_stage != stage: continue
            run = document(root,f'run-{campaign}.json'); report = document(root,f'report-{campaign}/report.json')
            methods = ['groops_pulses_ar'] if kind=='flight_ar_reference' else ['groops_log_drag_ou','groops_pulses']
            cases = [canonical(case) for case in run['planned_cases']]
            frozen_cases = [canonical(row['case']) for row in frozen['prepare_results'] if row['campaign']==kind]
            expected={(case,method) for case in cases for method in methods}
            actual=[(canonical(row['case']),row['method']) for row in run['runs']]
            if (len(cases)!=count//len(methods) or len(set(cases))!=len(cases)
                    or len(actual)!=count or set(actual)!=expected or sorted(cases)!=sorted(frozen_cases)
                    or frozen['campaign_case_counts'][kind]!=len(cases) or sorted(run['methods'])!=methods
                    or run.get('status')!='complete' or run.get('complete') is not True
                    or run.get('source_hash')!=SOURCE or run.get('protocol_hash')!=PROTOCOL
                    or run.get('selection_hash')!=selection['selection_hash']
                    or report.get('selection_hash')!=selection['selection_hash']):
                raise ValueError('Incomplete, duplicate or unfrozen evaluation design: '+campaign)
            expected_metrics.update((campaign,case,method) for case,method in expected)
            for row in run['runs']:
                item=by_key.get((campaign,canonical(row['case']),row['method']),{})
                if (item.get('source_fit_record')!=row['fit_record']
                        or item.get('source_evaluation_record')!=row.get('evaluation_record')):
                    raise ValueError('Compact metrics no longer identify the archived fit/evaluation')
    if len(metrics)!=1650 or set(by_key)!=expected_metrics: raise ValueError('Expected all 1650 unique compact fit rows')
    if Counter(map(canonical,rows(root,'calibration-scores.jsonl'))) != Counter(map(canonical,calibration_rows)):
        raise ValueError('Calibration rows omitted or changed')
    expected_failures=[]
    for row in metrics:
        if not (row.get('status')=='complete' and row.get('converged') and row.get('covariance_valid') and row.get('evaluation_status')=='complete'):
            expected_failures.append({'phase':'evaluation','failure_kind':'invalid_or_unavailable_fit_or_evaluation',**row})
    expected_failures.extend({'phase':'calibration','failure_kind':'invalid_candidate_arc_holdout',**row}
                             for row in calibration_rows if not row.get('valid'))
    failures=rows(root,'failures.jsonl')
    if (Counter(map(canonical,failures))!=Counter(map(canonical,expected_failures))
            or summaries['failure_counts']!=dict(Counter(row['phase'] for row in failures))):
        raise ValueError('Failure publication omits or changes terminal records')
    return {**verified,'verified_evaluation_rows':len(metrics),'verified_calibration_rows':len(calibration_rows),
            'verified_failure_rows':len(failures)}


def verify_runtime(project, protocol):
    expected=protocol['source']['files']
    if len(expected)!=89 or canonical(expected)!=SOURCE: raise ValueError('Unexpected frozen source map')
    manifest=read(project/METADATA/'manifest.json')
    mapping={row['source_path']:row for row in manifest['files']}
    eggs={name for name in expected if name.startswith('src/orbit_poc.egg-info/')}
    if manifest.get('source_hash')!=SOURCE or set(mapping)!=eggs: raise ValueError('Archived package metadata mapping differs')
    actual=set()
    for directory in ('src','scripts','groops/extension','groops/templates','configs'):
        for path in (project/directory).rglob('*'):
            if path.is_file() and path.suffix in {'.py','.cpp','.h','.hpp','.sh','.xml','.json','.yaml','.yml','.txt'}:
                name=path.relative_to(project).as_posix()
                if not name.startswith('src/orbit_poc.egg-info/'): actual.add(name)
    for name in ('pyproject.toml','tudat-linux-64.lock.txt','groops/linux-64.lock.txt','groops/python-requirements.lock.txt'):
        if (project/name).is_file(): actual.add(name)
    if actual != set(expected)-eggs: raise ValueError('Runtime source paths differ from frozen snapshot')
    for name,digest in expected.items():
        if name in eggs:
            record=mapping[name]
            if record['sha256']!=digest or Path(record['file']).name!=record['file']:
                raise ValueError('Invalid package metadata archive entry')
            path=integrity.member(project,METADATA+'/'+record['file'])
        else: path=integrity.member(project,name)
        if sha(path)!=digest: raise ValueError('Frozen runtime changed: '+name)
    return 89


def remote_status():
    # Only this already-existing status file is polled. Missing status exits SSH
    # unsuccessfully and consumes the bounded transient budget; nothing is launched.
    return json.loads(command(SSH+[HOST,'cat -- '+shlex.quote(REMOTE_STATUS)],timeout=55))


def check_remote(record):
    binding=record.get('binding',{})
    expected={'campaign':DATA+'/campaign-v3-03','project':BASE+'/project-test-candidate-03-complete',
        'collector':BASE+'/publication-audit-03/harvest_v3.py','output':REMOTE_BUNDLE,
        'source_sha256':SOURCE,'protocol_hash':PROTOCOL,'native_sha256':NATIVE,
        'collector_sha256':integrity.COLLECTOR,'renderer_sha256':integrity.RENDERER}
    if (binding!=expected or record.get('estimators_launched') is not False
            or record.get('helper_sha256')!=VERIFIER_SHA):
        raise ValueError('Remote handoff binding/identity differs')
    state=record.get('status')
    if state in ('blocked','failed','interrupted'): raise ValueError('Remote handoff terminated: '+str(record.get('phase')))
    if state not in ('waiting','running','complete'): raise ValueError('Unknown remote handoff state')
    if state=='complete':
        verification=record.get('verification',{})
        if (verification.get('expected_evaluation_fits')!=1650 or verification.get('verified_metric_rows')!=1650
                or verification.get('verified_figures')!=6 or not verification.get('bundle_content_hash')
                or record.get('upstream',{}).get('source_files_rehashed')!=89
                or not verification.get('publication_sha256')):
            raise ValueError('Remote handoff lacks completed verification')
    return state


def copy_to_repo(staging, repo, expected):
    target=repo/'runs/v3'
    if target.exists() or target.is_symlink():
        verified=verify_bundle(target)
        if verified['publication_sha256']!=expected: raise ValueError('Existing local v3 differs; preserved')
        return verified
    target.parent.mkdir(parents=True,exist_ok=True)
    # Linux/WSL renameat2 supplies NOREPLACE, closing the check/rename race even
    # when a different process creates an empty destination directory.
    libc=ctypes.CDLL(None,use_errno=True)
    if not hasattr(libc,'renameat2'): raise RuntimeError('Atomic no-replace directory rename is unavailable')
    if libc.renameat2(-100,os.fsencode(staging),-100,os.fsencode(target),1):
        error=ctypes.get_errno(); raise OSError(error,os.strerror(error),str(target))
    return verify_bundle(target)


def check_local_repo(repo):
    if repo.is_symlink() or git(repo,'rev-parse','--show-toplevel')!=str(repo):
        raise ValueError('Expected the existing local repository root')
    # No local README, v2, or tracked v3 edits may be covered up by this task.
    git(repo,'diff','--exit-code','HEAD','--','README.md','results.html','runs/v2','runs/v3')
    if (repo/'runs').is_symlink(): raise ValueError('Local runs directory cannot be a symlink')


def wait_for_bundle(repo,journal,*,max_hours=336,sleeper=time.sleep,monotonic=time.monotonic):
    check_local_repo(repo); protected=protected_tree(repo)
    deadline=monotonic()+max_hours*3600; transient_failures=0; last=None
    journal.record('waiting','remote_handoff',finite_wait_hours=max_hours)
    while True:
        if monotonic()>=deadline: raise TimeoutError('Finite handoff wait elapsed')
        try: record=remote_status()
        except (RuntimeError,subprocess.TimeoutExpired,OSError) as error:
            transient_failures+=1
            if transient_failures>=5: raise RuntimeError('Five consecutive transient SSH failures; no further retry') from error
            sleeper(min(60,max(0,deadline-monotonic()))); continue
        state=check_remote(record)
        transient_failures=0
        if state=='complete': break
        signature=(record.get('sequence'),state,record.get('phase'))
        if signature!=last:
            journal.record('waiting','remote_handoff',remote_sequence=record.get('sequence'),remote_phase=record.get('phase'))
            last=signature
        sleeper(min(60,max(0,deadline-monotonic())))
    expected=record['verification']['publication_sha256']
    if (repo/'runs/v3').exists():
        verified=verify_bundle(repo/'runs/v3')
        if (verified['publication_sha256']!=expected
                or verified['bundle_content_hash']!=record['verification']['bundle_content_hash']):
            raise ValueError('Existing local v3 conflicts with remote handoff')
        verify_runtime(repo,document(repo/'runs/v3','protocol.json'))
        return journal.record('bundle_ready','verified_existing_local',verification=verified,remote_handoff=record)
    (repo/'runs').mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.v3-transfer-',dir=repo/'runs'))
    journal.record('transferring','rsync',staging=str(staging),remote_handoff=record)
    command(['rsync','-a','--safe-links','--timeout=60','-e',shlex.join(SSH),HOST+':'+REMOTE_BUNDLE+'/',str(staging)+'/'],timeout=3600)
    verified=verify_bundle(staging)
    if (verified['publication_sha256']!=expected or verified['bundle_content_hash']!=record['verification']['bundle_content_hash']):
        raise ValueError('Transferred manifest differs from terminal handoff')
    # Capture a changed remote terminal manifest before moving local bytes into place.
    after=remote_status()
    if check_remote(after)!='complete' or after['verification']!=record['verification']:
        raise ValueError('Remote handoff changed during transfer')
    verify_runtime(repo,document(staging,'protocol.json'))
    installed=copy_to_repo(staging,repo,expected)
    if protected_tree(repo)!=protected: raise ValueError('Protected local v2 bytes changed during transfer')
    return journal.record('bundle_ready','verified_local_bundle',verification=installed,remote_handoff=record)


def git(project,*args,auth=False,timeout=120):
    config=['-c','credential.helper=','-c',f'credential.helper=!"{GH}" auth git-credential'] if auth else []
    return command(['git',*config,'-C',str(project),*args],timeout=timeout).strip()


def readme_result(old,verification):
    start='## GROOPS comparison protocol v3\n'; end='## Completed v2 campaign\n'
    if old.count(start)!=1 or old.count(end)!=1: raise ValueError('Unexpected README structure; preserve it')
    before,rest=old.split(start,1); previous,after=rest.split(end,1)
    section=('## GROOPS comparison protocol v3\n\n'
        'The completed [candidate03 comparison report](runs/v3/index.html) records all\n'
        '1,650 planned evaluation attempts: 1,600 synthetic, 20 mixed-force stress,\n'
        '24 float-ambiguity flight and six separate native ambiguity-resolution references.\n'
        'Failed, excluded and incomplete fits remain explicit; completion does not\n'
        'establish accuracy improvement or valid uncertainty calibration.\n\n'
        'Read the paired seed intervals, fixed-epoch coverage, calibration boundaries\n'
        'and failure counts before interpreting results. Flight SLR is independent\n'
        'validation; GNV1B agreement shares GPS information and is not truth error.\n'
        'The latent atmospheric quantity is an effective drag correction. Formal\n'
        'covariance is conditional on selected settings and fixed observation weights.\n\n'
        'The bundle preserves [frozen protocol and provenance](runs/v3/file-inventory.json),\n'
        '[per-fit results and resources](runs/v3/metrics.jsonl),\n'
        '[all failures](runs/v3/failures.jsonl), and the\n'
        '[publication manifest](runs/v3/publication.json). Existing v2 results remain unchanged.\n\n'
        f'Publication manifest SHA256: `{verification["publication_sha256"]}`.\n\n')
    if start+previous != section and hashlib.sha256((start+previous).encode()).hexdigest()!=README_PENDING_SHA:
        raise ValueError('README v3 section changed from the predeclared pending text; preserve manual edits')
    return before+section+end+after


def protected_tree(project):
    paths=git(project,'ls-files','-z','--','runs/v2','results.html').split('\0')
    return {name:sha(integrity.member(project,name)) for name in paths if name}


def pr_request(body=None):
    args=[GH,'api','repos/FlorianPfaff/orbit-smoothing-poc/pulls/1']
    if body is not None: args+=['--method','PATCH','--input','-']
    return json.loads(command(args,input=json.dumps({'body':body}) if body is not None else None,timeout=60))


def check_pr(pr,commit=None):
    if (pr.get('number')!=1 or pr.get('state')!='open'
            or pr.get('head',{}).get('ref')!=BRANCH or pr.get('base',{}).get('ref')!='main'
            or any(pr.get(side,{}).get('repo',{}).get('full_name')!='FlorianPfaff/orbit-smoothing-poc' for side in ('head','base'))
            or (commit is not None and pr.get('head',{}).get('sha')!=commit)):
        raise ValueError('Existing PR1 identity/head/base differs; do not modify it')


def pr_body(commit,verification):
    root=f'https://github.com/FlorianPfaff/orbit-smoothing-poc/blob/{commit}/runs/v3'
    return ('The matched GROOPS comparison has completed all 1,650 planned evaluation attempts: '
        '1,600 synthetic primary, 20 mixed-force stress, 24 float-ambiguity flight and six separate native '
        'ambiguity-resolution references. Failed, invalid, excluded and incomplete results are retained. '
        'Execution completion does not establish an accuracy improvement or calibrated uncertainty.\n\n'
        f'[HTML comparison report]({root}/index.html), [all per-fit results]({root}/metrics.jsonl), '
        f'[failures]({root}/failures.jsonl), [bundle manifest]({root}/publication.json).\n\n'
        'The primary scenario is 500 km, disturbed atmosphere, 11–13 h blackout, with 50 independent paired seeds. '
        'Read the paired confidence intervals, fixed-epoch coverage and calibration adequacy disclosures. '
        'Unresolved improving calibration boundaries withhold superiority claims. Formal covariance is local Gaussian '
        'uncertainty conditional on selected hyperparameters, fixed weights/products and modeled forces; it excludes '
        'model-selection uncertainty. No superiority claim is made here.\n\n'
        'Flight SLR is withheld independent evidence in a limited May quiet/storm event study. GPS-derived GNV1B '
        'agreement shares observations and is not truth error or flight truth coverage. The native 20-minute pulse '
        'ambiguity-resolution arm remains a separate reference; the atmospheric latent variable is an effective '
        'drag correction. Published v2 bytes and the frozen runtime remain unchanged.\n\n'
        f'Frozen source: `{SOURCE}`\n\nProtocol: `{PROTOCOL}`\n\nNative: `{NATIVE}`\n\n'
        f'Publication manifest SHA256: `{verification["publication_sha256"]}`\n\n'
        f'Bundle content hash: `{verification["bundle_content_hash"]}`\n\n'
        'Publication checks verified the exact archived file set and hashes, original gzip payloads, all 1,650 unique '
        'case/method rows against frozen input selections, failure retention and the actual figure provenance. '
        'Bulky source observations and native intermediates remain outside Git; publication did not reread every raw input.\n')


def publish(repo,journal):
    check_local_repo(repo)
    bundle=repo/'runs/v3'; verified=verify_bundle(bundle); protocol=document(bundle,'protocol.json')
    verify_runtime(repo,protocol)
    # Require the explicit wait step to have verified the same remote bundle.
    prior=journal.previous or {}
    if prior.get('status') not in ('bundle_ready','published') or prior.get('verification',{}).get('publication_sha256')!=verified['publication_sha256']:
        raise ValueError('Publish requires matching terminal bundle_ready/published worker receipt')
    if not Path(GH).is_file(): raise ValueError('Established Windows gh credential helper is unavailable')
    check_pr(pr_request())
    temporary=Path(tempfile.mkdtemp(prefix='v3-publish-',dir=journal.directory)); clone=temporary/'repo'
    journal.record('publishing','clone',clone=str(clone),verification=verified)
    command(['git','-c','credential.helper=','-c',f'credential.helper=!"{GH}" auth git-credential',
             'clone','--single-branch','--branch',BRANCH,REPOSITORY,str(clone)],timeout=600)
    if (git(clone,'remote','get-url','origin')!=REPOSITORY or git(clone,'branch','--show-current')!=BRANCH
            or git(clone,'status','--porcelain')): raise ValueError('Clone is not clean on the expected public branch')
    base=git(clone,'rev-parse','HEAD'); before=protected_tree(clone)
    if not before: raise ValueError('Expected preserved v2 tree is absent')
    verify_runtime(clone,protocol)
    target=clone/'runs/v3'
    if target.exists():
        current=verify_bundle(target)
        if current['publication_sha256']!=verified['publication_sha256']: raise ValueError('Public branch already contains conflicting v3 bytes')
    else: shutil.copytree(bundle,target)
    readme=clone/'README.md'; old=readme.read_bytes().decode('utf-8'); updated=readme_result(old,verified)
    if old!=updated: readme.write_bytes(updated.encode('utf-8'))
    git(clone,'add','-f','--','runs/v3'); git(clone,'add','--','README.md')
    changed=[name for name in git(clone,'diff','--cached','--name-only','-z').split('\0') if name]
    if any(name!='README.md' and not name.startswith('runs/v3/') for name in changed):
        raise ValueError('Unexpected staged publication path')
    verify_bundle(target); verify_runtime(clone,protocol)
    if protected_tree(clone)!=before: raise ValueError('Protected v2 bytes changed')
    git(clone,'diff','--cached','--check')
    if changed:
        for field in ('name','email'):
            git(clone,'config','user.'+field,git(repo,'config','user.'+field))
        git(clone,'commit','-m','Publish completed GROOPS candidate03 comparison')
    commit=git(clone,'rev-parse','HEAD')
    if git(clone,'status','--porcelain'): raise ValueError('Publication clone became dirty')
    # Refuse a concurrent branch update, even if Git could fast-forward through it.
    remote=git(clone,'ls-remote','origin','refs/heads/'+BRANCH,auth=True).split()
    if len(remote)!=2 or remote[0]!=base: raise ValueError('Public branch advanced; refusing push without review')
    if changed:
        journal.record('publishing','push',clone=str(clone),base_commit=base,commit=commit,verification=verified)
        git(clone,'push','origin',BRANCH,auth=True,timeout=600)  # deliberately no force/lease
    git(clone,'fetch','origin',BRANCH,auth=True,timeout=600)
    if git(clone,'rev-parse','refs/remotes/origin/'+BRANCH)!=commit:
        raise ValueError('Remote head does not identify the verified publication commit')
    # Verify the fetched public tree, not merely the pre-push working directory.
    checkout=temporary/'remote-verified'
    git(clone,'worktree','add','--detach',str(checkout),'refs/remotes/origin/'+BRANCH)
    published=verify_bundle(checkout/'runs/v3'); verify_runtime(checkout,protocol)
    if (published['publication_sha256']!=verified['publication_sha256'] or protected_tree(checkout)!=before
            or (checkout/'README.md').read_bytes()!=updated.encode('utf-8')): raise ValueError('Fetched publication bytes differ')
    details=dict(verification=published,commit=commit,base_commit=base,
        repository=REPOSITORY,branch=BRANCH,pull_request='https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/1',
        report_url=f'https://github.com/FlorianPfaff/orbit-smoothing-poc/blob/{commit}/runs/v3/index.html',
        protected_v2_files=len(before),clone=str(clone),external_publication_performed=bool(changed),repository_bytes_verified=True)
    journal.record('published_repo','updating_existing_pr',**details)
    try:
        existing=pr_request();check_pr(existing,commit)
        body=pr_body(commit,published);body_hash=hashlib.sha256(body.encode()).hexdigest()
        if existing.get('body')!=body:
            response=pr_request(body);check_pr(response,commit)
            if response.get('body')!=body: raise ValueError('PR PATCH response body differs')
        confirmed=pr_request();check_pr(confirmed,commit)
        if confirmed.get('body')!=body or confirmed.get('draft')!=existing.get('draft'):
            raise ValueError('Published PR body/draft state differs from requested update')
    except Exception as error:
        return journal.record('published_repo_pr_update_failed','existing_pr_update',**details,
            reason=f'{type(error).__name__}: {error}',automatic_retry=False)
    return journal.record('published','remote_bytes_and_pr_verified',**details,pr_body_sha256=body_hash)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--wait-for-bundle',action='store_true'); mode.add_argument('--publish',action='store_true')
    parser.add_argument('--repo',type=Path,default=DEFAULT_REPO)
    parser.add_argument('--control',type=Path,default=DEFAULT_CONTROL)
    parser.add_argument('--max-wait-hours',type=float,default=336)
    args=parser.parse_args(); repo=args.repo.resolve(); control=args.control.resolve()
    if not 0<args.max_wait_hours<=8760: parser.error('Finite wait must be within one year')
    if control==repo or repo in control.parents: parser.error('Worker control must be outside the public repository')
    def interrupted(signum,frame): raise KeyboardInterrupt('Signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    try:
        with lock(control):
            journal=Journal(control,repo)
            if journal.previous and journal.previous.get('status') in ('failed','interrupted','publishing','published_repo','published_repo_pr_update_failed'):
                raise ValueError('Prior failed/interrupted/publishing receipt requires explicit reconciliation; no automatic retry')
            try:
                result=wait_for_bundle(repo,journal,max_hours=args.max_wait_hours) if args.wait_for_bundle else publish(repo,journal)
            except BaseException as error:
                if not isinstance(error,(Exception,KeyboardInterrupt)): raise
                prior_phase=read(journal.path).get('phase') if journal.path.exists() else None
                result=journal.record('interrupted' if isinstance(error,KeyboardInterrupt) else 'failed',
                    'wait_or_transfer' if args.wait_for_bundle else 'publication',reason=f'{type(error).__name__}: {error}',
                    completion_claim=False,remote_push_may_have_completed=bool(args.publish and prior_phase=='push'))
            print(json.dumps(result,indent=2))
            return 0 if result['status'] in ('bundle_ready','published') else 2
    except Exception as error:
        print(json.dumps({'status':'not_started','reason':str(error),'existing_status_preserved':True})); return 2


if __name__=='__main__': raise SystemExit(main())
