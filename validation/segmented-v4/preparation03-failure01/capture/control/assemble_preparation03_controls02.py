"""Seal direct-path preparation controls after independently audited validation04."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json

ROOT = Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
V = ROOT/'validation-04'
C = ROOT/'preparation-03/control'
BASE_EXECUTION = '526e8f704650eccc69863669ac4068c1c192f38b990a5a2190eba81d4a22007d'
CONFIG = 'e23eb3a1b4eafc6c1c279183292513b87e64a366061ac6ef645987700c193fac'
FREEZE = '87ad55dcd0c4329cb4e37a37adfe3871cb85d3fb88e8a46b3cff388aa17e9f29'
PRODUCTS = ROOT/'deployment-product-preflight-01/receipt.json'
PRODUCTS_SHA = 'd5d463e4d67dd1fb689020b7177c54798698596f87be0641adce3dffcd217369'
HELPERS = ('run_segmented_preparation01.py', 'launch_segmented_preparation01.py', 'check_preparation_state01.py', 'probe_segmented_preparation02.py', 'smoke_segmented_preparation01.py')

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(path): return {'path': str(path), 'sha256': sha(path)}
def require(ok, why):
    if not ok: raise ValueError(why)
def checked(item):
    require(isinstance(item, dict) and set(item) == {'path', 'sha256'}, 'Exact pin required')
    path = Path(item['path'])
    require(path.is_absolute() and path.is_file() and sha(path) == item['sha256'], 'Changed pinned file: '+str(path))
    return json.loads(path.read_text())
def save(path, value):
    with path.open('x') as stream: json.dump(value, stream, indent=2, sort_keys=True); stream.write('\n')
    return pin(path)
def plain(item): return {key: item[key] for key in ('path', 'sha256')}

def assemble(audit_pin, install_pin, helper_manifest_pin):
    # The helper manifest preserves exact bytes of previously audited controls.
    helper_manifest = checked(helper_manifest_pin)
    require(set(helper_manifest) == set(HELPERS), 'Unexpected preparation helper set')
    for name, expected in helper_manifest.items():
        require(expected == pin(C/name), 'Preparation helper bytes differ')
    base_pin = {'path': str(V/'control/execution.json'), 'sha256': BASE_EXECUTION}
    base = checked(base_pin)
    config_pin = {'path': str(V/'control/segmented-v4.json'), 'sha256': CONFIG}
    config = checked(config_pin)
    freeze_pin = {'path': str(V/'control/source-freeze.json'), 'sha256': FREEZE}
    freeze = checked(freeze_pin)
    audit = checked(audit_pin); installed = checked(install_pin)
    require(audit.get('schema') == 'orbit-poc-segmented-validation-terminal-independent-review-v1' and audit.get('consistency_passed') is True and audit.get('scientific_status') == 'passed_scoped_checks' and audit.get('cleanup_verified') is True, 'Passed independent full-suite audit required')
    require(installed['schema'] == 'orbit-poc-preparation03-product-cache-install-v2' and installed['independent_terminal_audit'] == audit_pin and installed['network_requests'] == installed['native_propagations'] == 0, 'Audited cache installation differs')
    require(installed['cache'] == config['preparation']['cache_dir'] == base['paths']['build'], 'Direct cache identity differs')
    for key in ('root', 'source', 'control', 'native_source', 'build', 'binaries', 'run', 'temporary'):
        require(str(V) == base['paths'][key] or V in Path(base['paths'][key]).parents, 'Direct validation04 path required: '+key)
    require(Path(base['paths']['control']) == V/'control' and Path(config['output_dir']) == Path(base['paths']['run']), 'Canonical output differs')
    require(C.is_dir() and not C.is_symlink() and str(C) == str(C.resolve()), 'Canonical separate control directory required')
    require(not (C/'pipeline.json').exists(), 'Preparation has already run')
    run = Path(base['paths']['run'])
    require(run.is_dir() and {p.name for p in run.iterdir()} == {'plan.json', 'validation'}, 'Fresh validation-only run inventory required')
    require(not (run/'plan.json').is_symlink() and not (run/'validation').is_symlink(), 'Direct original validation entries required')
    generated = ('cache-seed.json', 'execution.json', 'plan.json', 'pins.json', 'probe-plan.json', 'smoke-plan.json', 'assembly.json')
    require(all(not (C/name).exists() and not (C/name).is_symlink() for name in generated), 'Fresh unassembled controls required')
    source_digest = freeze['comparison_source']['sha256']
    require(config['segmented_runtime']['source_sha256'] == config['dense_runtime']['source_sha256'] == source_digest, 'Source/config identity differs')
    prod_pin = {'path': str(PRODUCTS), 'sha256': PRODUCTS_SHA}; products = checked(prod_pin)
    require(products['status'] == 'passed' and products['product_count'] == len(products['records']) == 20, 'Product preflight differs')
    actual = {Path(row['installed']['copied_product']['path']).name: row for row in installed['entries']}
    require(len(actual) == len(installed['entries']) == 20, 'Installed product inventory differs')
    rows = []; runtime_additions = {}
    for n, original in enumerate(products['records']):
        row = actual[original['name']]; dst = row['installed']['copied_product']; record = row['installed']['copied_record']
        require(dst['path'] == str(Path(config['preparation']['cache_dir'])/'gnss'/original['name']) and dst['sha256'] == original['sha256'] and Path(dst['path']).stat().st_size == original['bytes'], 'Product destination/bytes differ')
        require(record['path'] == dst['path']+'.source.json', 'Acquisition sidecar pairing differs')
        for role, value in (('product', dst), ('verification_record', record)):
            require(pin(value['path']) == value, 'Installed product or record changed')
            runtime_additions['preparation03_'+role+'_'+str(n)] = value
        rows.append({'source': {'path': original['path'], 'sha256': original['sha256']}, 'destination': dst, 'bytes': original['bytes']})
    expected_names = {Path(v['path']).name for v in runtime_additions.values()}
    require({p.name for p in (Path(config['preparation']['cache_dir'])/'gnss').iterdir()} == expected_names, 'Exact40 cache members required')
    seed = {'schema': 'orbit-poc-preparation03-direct-cache-seed-v1', 'status': 'staged_unexecuted', 'canonical_cache_matches_frozen_config': True, 'old_validation_execution_unchanged': True, 'native_or_preparation_launched': False, 'cache_path': config['preparation']['cache_dir'], 'input_plan': {'config': config_pin, 'products': prod_pin}, 'products': rows, 'installation': install_pin, 'scope': 'This cache staging did not run native propagation or preparation. The prerequisite full validation ran separately. Source records retain their exact earlier offline-verification bytes and are not new acquisition receipts.'}
    seed_pin = save(C/'cache-seed.json', seed)
    e = copy.deepcopy(base)
    e['read_only_bindings'].append({'source': str(C), 'target': str(C)})
    for key, value in runtime_additions.items():
        require(key not in e['runtime_artifacts'], 'Duplicate runtime role'); e['runtime_artifacts'][key] = value
    extras = {'validation04_execution': base_pin, 'preparation03_cache_seed': seed_pin, 'preparation03_cache_install': install_pin, 'preparation03_validation_audit': audit_pin, 'preparation03_helper_manifest': helper_manifest_pin, 'preparation03_assembler': pin(__file__)}
    extras.update({'preparation03_helper_'+str(n): helper_manifest[name] for n, name in enumerate(HELPERS)})
    extras.update({'preparation03_terminal_'+name: plain(value) for name, value in audit['artifacts'].items()})
    for key, value in extras.items():
        require(key not in e['runtime_artifacts'], 'Duplicate runtime role'); require(sha(value['path']) == value['sha256'], 'Added runtime pin changed'); e['runtime_artifacts'][key] = value
    execution_pin = save(C/'execution.json', e)
    check_root = Path(base['paths']['temporary'])/'preparation-03-checks'
    require(not check_root.exists(), 'Fresh preparation checker output required')
    driver_pin = pin(V/'control/owned_driver09.py')
    launch = checked(plain(audit['artifacts']['launch_plan']))
    plan = {'schema': 'orbit-poc-segmented-preparation-owned-plan-v1', 'execution': execution_pin, 'driver': driver_pin, 'runner': helper_manifest['run_segmented_preparation01.py'], 'source_freeze': freeze_pin, 'config': config_pin, 'checker': helper_manifest['check_preparation_state01.py'], 'validation_audit': audit_pin, 'controller': plain(audit['artifacts']['controller']), 'pipeline': plain(audit['artifacts']['cli_pipeline']), 'global_lock': launch['global_lock'], 'control_root': str(C), 'check_output_root': str(check_root), 'wall_limit_seconds': 129600}
    plan_pin = save(C/'plan.json', plan)
    spec = importlib.util.spec_from_file_location('existing_preparation_controller', C/'run_segmented_preparation01.py'); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    require(module.load_plan(plan_pin['path'], plan_pin['sha256']) == plan, 'Existing preparation controller rejected sealed plan')
    pins = {'plan': plan_pin, 'driver_sha256': helper_manifest['run_segmented_preparation01.py']['sha256'], 'execution_sha256': execution_pin['sha256'], 'control_root': str(C)}
    pins_pin = save(C/'pins.json', pins)
    scratch = V/'staging/preparation-03/startup-01'
    require(not scratch.exists(), 'Fresh startup output required')
    probe = {'schema': 'orbit-poc-preparation-startup-plan-v1', 'helper': helper_manifest['probe_segmented_preparation02.py'], 'config': config_pin, 'cache_seed': seed_pin, 'products': prod_pin, 'source_sha256': source_digest, 'output': str(scratch/'temporary/probe-result')}
    probe_pin = save(C/'probe-plan.json', probe)
    smoke = {'schema': 'orbit-poc-preparation-owned-startup-smoke-v1', 'execution': execution_pin, 'driver': driver_pin, 'probe_plan': probe_pin, 'helper': helper_manifest['smoke_segmented_preparation01.py'], 'global_lock': launch['global_lock'], 'output': str(scratch)}
    smoke_pin = save(C/'smoke-plan.json', smoke)
    receipt = {'schema': 'orbit-poc-preparation03-controls-assembly-v1', 'status': 'sealed_unexecuted', 'base_execution': base_pin, 'execution': execution_pin, 'plan': plan_pin, 'pins': pins_pin, 'probe': probe_pin, 'smoke': smoke_pin, 'cache_seed': seed_pin, 'audit': audit_pin, 'install': install_pin, 'helpers': helper_manifest_pin, 'runtime_pin_count': len(e['runtime_artifacts']), 'base_runtime_pins_unchanged': all(e['runtime_artifacts'][key] == value for key, value in base['runtime_artifacts'].items()), 'source': freeze['source']['sha256'], 'source_configuration': config_pin, 'native_rebuild_or_substitution': False, 'preparation_or_fit_launched': False}
    return save(C/'assembly.json', receipt)

def main(argv=None):
    p = argparse.ArgumentParser()
    for key in ('audit', 'install', 'helpers'):
        p.add_argument('--'+key, required=True); p.add_argument('--'+key+'-sha256', required=True)
    a = p.parse_args(argv); pins = [dict(path=getattr(a, key), sha256=getattr(a, key+'_sha256')) for key in ('audit', 'install', 'helpers')]
    print(json.dumps(assemble(*pins)))
if __name__ == '__main__': main()
