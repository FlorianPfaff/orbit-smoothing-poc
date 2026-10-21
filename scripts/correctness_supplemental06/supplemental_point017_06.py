#!/usr/bin/env python3
"""One separately pinned diagnostic after required06 validation and reporting close.

Never imports this result into prescribed acceptance gates. No scheduler or
implicit launch: invoke only after the coordinating task explicitly authorizes
this supplemental run and seals the terminal evidence in its plan.
"""
from pathlib import Path
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import signal

SCHEMA = 'orbit-poc-supplemental-point017-plan-v1'
INPUT_ROLES = ('profile', 'variational', 'reference', 'density')
REQUIRED_STEPS = ('clone', 'checkout', 'build', 'native-tests', 'correction-regression-tests',
    'synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses', 'flight-refinement',
    'eccentric-24h-refinement', 'objective-log_drag_ou', 'objective-pulses',
    'nuisance-replay', 'nuisance-replay-candidate1-point012')


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def artifact(path):
    return {'path': str(path), 'sha256': sha(path)}


def checked(pin, label, *, json_data=True):
    require(isinstance(pin, dict) and set(pin) == {'path', 'sha256'}
            and isinstance(pin['path'], str) and Path(pin['path']).is_absolute()
            and '..' not in Path(pin['path']).parts, 'Invalid artifact: ' + label)
    require(sha(pin['path']) == pin['sha256'], 'Artifact changed: ' + label)
    return json.loads(Path(pin['path']).read_text()) if json_data else None


def validate_terminal(plan, execution, pins):
    """Terminal failure is valid diagnostic context; unfinished work is not."""
    pipeline = checked(plan['validation_pipeline'], 'required validation')
    post = checked(plan['postprocess_pipeline'], 'required postprocess')
    postplan = checked(plan['postprocess_plan'], 'postprocess plan')
    paths = execution['paths']
    require(plan['validation_pipeline']['path'] == str(Path(paths['run'])/'pipeline.json'),
            'Wrong required validation pipeline')
    require(pipeline.get('status') in ('passed', 'failed') and pipeline.get('finished_at')
            and pipeline.get('final_cleanup', {}).get('verified') is True,
            'Required validation is not terminal with verified cleanup')
    require(pipeline.get('required_pins', {}).get('path') == plan['candidate_pins']['path']
            and pipeline.get('required_pins', {}).get('sha256') == plan['candidate_pins']['sha256']
            and pipeline.get('execution', {}).get('sha256') == plan['execution']['sha256']
            and pipeline.get('source', {}).get('sha256') == pins['source_sha256'],
            'Required validation identity differs')
    # Every prescribed step must have been attempted. This diagnostic cannot
    # become an early substitute when build/native-test failure stopped the suite.
    steps = pipeline.get('steps', [])
    require([s.get('name') for s in steps] == list(REQUIRED_STEPS)
            and all(s.get('finished_at') and s.get('cleanup', {}).get('verified') is True for s in steps),
            'The complete prescribed suite has not reached terminal cleanup')
    require(pipeline.get('native') == plan['native'], 'Wrong corrected native executable')
    require(pipeline.get('resume') == {'status': 'not_applicable', 'reason': 'no_campaign_running'},
            'Required validation has invalid campaign attribution')
    postroot = Path(paths['root'])/'postprocess-06-01'
    require(plan['postprocess_pipeline']['path'] == str(postroot/'pipeline.json')
            and postplan.get('output_root') == str(postroot), 'Wrong postprocess output')
    require(postplan.get('schema') == 'orbit-poc-correctness-postprocess06-plan-v1'
            and postplan.get('execution') == plan['execution']
            and postplan.get('candidate_pins') == plan['candidate_pins']
            and postplan.get('source_sha256') == pins['source_sha256'], 'Wrong postprocess plan identity')
    require(post.get('plan', {}).get('path') == plan['postprocess_plan']['path']
            and post.get('plan', {}).get('sha256') == plan['postprocess_plan']['sha256']
            and post.get('validation_pipeline', {}).get('sha256') == plan['validation_pipeline']['sha256'],
            'Postprocess did not consume the pinned terminal validation')
    require(post.get('status') in ('completed', 'failed') and post.get('finished_at'),
            'Required postprocessing is not terminal')
    require([s.get('name') for s in post.get('steps', [])] == ['audit', 'report', 'collect']
            and all(s.get('finished_at') and s.get('cleanup_verified') is True for s in post['steps']),
            'Postprocess helpers have not all reached verified cleanup')
    return pipeline, post


def load_context(plan_path, plan_hash):
    require(sha(plan_path) == plan_hash, 'Supplemental plan changed')
    plan = json.loads(Path(plan_path).read_text())
    fields = {'schema', 'runner_sha256', 'execution', 'candidate_pins', 'driver', 'validation_pipeline',
              'postprocess_pipeline', 'postprocess_plan', 'native', 'input_artifacts', 'output', 'timeout_seconds'}
    require(set(plan) == fields and plan['schema'] == SCHEMA, 'Unknown supplemental plan fields')
    require(plan['runner_sha256'] == sha(__file__), 'Supplemental runner changed')
    require(plan['timeout_seconds'] == 7500, 'Supplemental timeout changed')
    execution = checked(plan['execution'], 'execution')
    pins = checked(plan['candidate_pins'], 'candidate pins')
    checked(plan['driver'], 'driver', json_data=False)
    require(plan['driver']['path'] == str(Path(execution['paths']['control'])/'validate_candidate_06.py')
            and plan['driver']['sha256'] == pins['driver_sha256'], 'Wrong validation driver')
    spec = importlib.util.spec_from_file_location('supplemental_owned_driver06', plan['driver']['path'])
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    execution = driver.load_execution(plan['execution']['path'])
    pins = driver.load_required_pins(plan['candidate_pins']['path'], plan['execution']['path'])
    source = driver.verify_pins(pins, execution, plan['execution']['path'])
    require(plan['execution']['sha256'] == pins['execution_sha256'], 'Execution pin differs')
    require(execution['fit_cpu'] == 24, 'Supplemental fit must use CPU24')
    output = Path(execution['paths']['temporary'])/'supplemental-point017'
    require(plan['output'] == str(output), 'Supplemental output outside its separate directory')
    require(set(plan['input_artifacts']) == set(INPUT_ROLES), 'Four exact point017 inputs required')
    for role in INPUT_ROLES:
        pin = plan['input_artifacts'][role]
        require(pin == execution['runtime_artifacts']['extra_point017_'+role], 'Wrong point017 input: '+role)
        checked(pin, 'point017 '+role, json_data=False)
    profile = Path(plan['input_artifacts']['profile']['path'])
    require(profile.parent.name == 'point-017-direction-0.125-1'
            and profile.parent.parent.name == 'objective-log_drag_ou'
            and profile.parent.parent.parent.name == 'validation-05', 'Wrong diagnostic source failure')
    text = profile.read_text()
    for role in INPUT_ROLES[1:]:
        require(plan['input_artifacts'][role]['path'] in text, 'Point017 XML input differs: '+role)
    native = plan['native']
    require(isinstance(native, dict) and set(native) == {'path', 'sha256', 'build_manifest_sha256'}, 'Invalid native pin')
    path = Path(native['path'])
    require(path.parent == Path(execution['paths']['binaries'])
            and path.name == 'groops-'+native['sha256'][:16], 'Native path differs from corrected archive')
    require(sha(path) == native['sha256'], 'Corrected executable changed')
    manifest = Path(str(path)+'.build-manifest.json')
    require(sha(manifest) == native['build_manifest_sha256']
            and json.loads(manifest.read_text())['executable_sha256'] == native['sha256'], 'Corrected build manifest changed')
    validate_terminal(plan, execution, pins)
    return {'plan': plan, 'execution': execution, 'pins': pins, 'driver': driver, 'source': source,
            'output': output, 'receipt': Path(execution['paths']['control'])/'candidate06-supplemental-point017.json'}


def command(context):
    p, e = context['plan'], context['execution']
    paths = e['paths'];native = p['native']['path']
    return [e['runtime_artifacts']['control_python']['path'], paths['wrapper'],
            '--execution', p['execution']['path'], '--execution-sha256', p['execution']['sha256'], '--',
            '/usr/bin/taskset', '-c', '24', 'env', 'ORBIT_POC_CORRECTNESS_NATIVE='+native,
            'ORBIT_POC_V31_NATIVE='+native, 'ORBIT_POC_GROOPS='+native, paths['python'],
            str(Path(paths['source'])/'scripts/validate_numerics_nuisance.py'),
            '--source-profile', p['input_artifacts']['profile']['path'], '--native', native,
            '--output', str(context['output']/'replay'), '--allow-floor-limited']


def run(context, plan_path, plan_hash):
    p, e, d = context['plan'], context['execution'], context['driver']
    output, receipt = context['output'], context['receipt']
    require(not output.exists() and not output.is_symlink() and not receipt.exists() and not receipt.is_symlink(),
            'Supplemental output or receipt already exists; no implicit retry')
    registry = [];caught = None;journal = {};old_handlers = {}
    with (Path(e['paths']['control'])/'candidate06-validation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        require(sha(plan_path) == plan_hash, 'Supplemental plan changed before launch')
        require(d.verify_pins(context['pins'], e, p['execution']['path']) == context['source'], 'Corrected source changed before launch')
        require(sha(p['native']['path']) == p['native']['sha256'], 'Corrected native changed before launch')
        validate_terminal(p, e, context['pins'])
        admission = d.admission(e)
        output.mkdir();(output/'tmp').mkdir()
        journal = {'schema': 'orbit-poc-supplemental-point017-run-v1', 'status': 'starting', 'started_at': d.stamp(),
            'plan': artifact(plan_path), 'runner_sha256': sha(__file__), 'admission': admission,
            'validation_pipeline': p['validation_pipeline'], 'postprocess_pipeline': p['postprocess_pipeline'],
            'native': p['native'], 'input_artifacts': p['input_artifacts'], 'argv': command(context),
            'timeout_seconds': 7500, 'scope': 'Supplemental exact validation05 point017 diagnostic only.',
            'required_gate_classifications_changed': False, 'covariance_authorized': False,
            'campaign_resume': 'not_applicable'}
        try:
            for number in (signal.SIGINT, signal.SIGTERM):
                old_handlers[number] = signal.getsignal(number);signal.signal(number, d.interrupted)
            d.save(receipt, journal)
            def guard_live():
                d.admission(e, registry)
            def on_started(pid):
                journal.update(status='running', pid=pid);d.save(receipt, journal)
            def on_finished(value):
                journal.update(value, child_finished_at=d.stamp());d.save(receipt, journal)
            env = dict(os.environ, PYTHONPATH=str(Path(e['paths']['source'])/'src'), PYTHONDONTWRITEBYTECODE='1',
                OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', TMPDIR=str(output/'tmp'))
            with (output/'runner.log').open('x') as log:
                code = d.supervise(journal['argv'], cwd=Path(e['paths']['source']), env=env, log=log, limit=7500,
                    guard_live=guard_live, on_started=on_started, on_finished=on_finished, registry=registry)
            journal['returncode'] = code
            require(sha(plan_path) == plan_hash, 'Supplemental plan changed during run')
            require(d.verify_pins(context['pins'], e, p['execution']['path']) == context['source'], 'Corrected source changed during run')
            validate_terminal(p, e, context['pins'])
            require(sha(p['native']['path']) == p['native']['sha256'], 'Corrected native changed during run')
            result_path = output/'replay/receipt.json'
            if result_path.is_file():
                result = json.loads(result_path.read_text());journal['diagnostic_receipt'] = artifact(result_path)
                require(result.get('schema') == 'orbit-poc-native-nuisance-validation-v1'
                        and result.get('native_sha256') == p['native']['sha256']
                        and result.get('source_profile') == p['input_artifacts']['profile']['path']
                        and result.get('source_profile_sha256') == p['input_artifacts']['profile']['sha256'],
                        'Supplemental result provenance differs')
                journal['strict_nuisance_converged'] = result.get('strict_nuisance_converged') is True
                journal['progress_only_floor_validated'] = result.get('progress_only_floor_validated') is True
                journal['diagnostic_checks_passed'] = result.get('passed') is True
            else:
                journal['diagnostic_checks_passed'] = False
            journal['status'] = 'completed' if code == 0 and journal['diagnostic_checks_passed'] else 'failed'
        except BaseException as error:
            caught = error;journal.update(status='failed', error=type(error).__name__+': '+str(error))
        finally:
            with d.cleanup_signals():
                failures = []
                for owned in registry:
                    try:
                        owned.cleanup(force=owned.child.poll() is None)
                    except BaseException as error:
                        failures.append(type(error).__name__+': '+str(error))
                journal['final_cleanup'] = {'verified': not failures, 'errors': failures,
                                            'commands': [owned.last_cleanup for owned in registry]}
                if failures:
                    journal['status'] = 'failed';caught = caught or RuntimeError('Supplemental cleanup unverified')
                journal['finished_at'] = d.stamp()
                try:
                    d.save(receipt, journal)
                finally:
                    for number, handler in old_handlers.items():
                        signal.signal(number, handler)
        if caught:
            raise caught
    return 0 if journal['status'] == 'completed' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True);parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args(argv)
    context = load_context(args.plan, args.plan_sha256)
    return run(context, args.plan, args.plan_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
