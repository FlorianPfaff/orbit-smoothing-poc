#!/usr/bin/env python3
"""Read-only startup checks in the actual preparation namespace; no propagation."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess

KEYS = {'schema', 'helper', 'config', 'cache_seed', 'products', 'source_sha256', 'output'}
TUDAT_CODE = '''import json,hashlib,runpy,sys
from pathlib import Path
import tudatpy
from tudatpy.dynamics import environment_setup,propagation_setup,simulator
from tudatpy.interface import spice
from tudatpy.astro.time_representation import DateTime
module=runpy.run_path(sys.argv[1],run_name="preparation_startup_only")
assert callable(module["run"])
files=[]
for role,item in zip(("tudatpy","environment_setup","propagation_setup","simulator","spice"),(tudatpy,environment_setup,propagation_setup,simulator,spice)):
 path=getattr(item,"__file__",None)
 p=Path(path).resolve() if path else None
 files.append({"role":role,"name":item.__name__,"file":None if p is None else {"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}})
print(json.dumps({"schema":"orbit-poc-tudat-startup-v1","status":"passed","imports":files,"truth_script_loaded_without_run":True,"propagations":0}))
'''


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pin(path):
    return {'path': str(path), 'sha256': sha(path)}


def checked(item):
    need(set(item) == {'path', 'sha256'} and Path(item['path']).is_absolute()
         and sha(item['path']) == item['sha256'], 'Startup artifact changed')
    return json.loads(Path(item['path']).read_text())


def inspect(plan, protocol, validation, load_config, *, run=subprocess.run, access=os.access, auxiliary_reuse=None, flight_reuse=None, cached_fetch=None):
    need(set(plan) == KEYS and plan['schema'] == 'orbit-poc-preparation-startup-plan-v1', 'Unknown startup plan')
    need(plan['helper'] == pin(Path(__file__).resolve()), 'Startup helper differs')
    checked(plan['config']); seed = checked(plan['cache_seed']); products = checked(plan['products'])
    cfg = load_config(plan['config']['path']); source = Path(cfg.segmented_runtime.source_root)
    root = Path(cfg.output_dir); cache = Path(cfg.preparation.cache_dir)
    need(cfg.segmented_runtime.source_sha256 == cfg.dense_runtime.source_sha256 == plan['source_sha256'], 'Startup source identity differs')
    need(seed['status'] == 'staged_unexecuted' and seed['canonical_cache_matches_frozen_config'] is True
         and seed['old_validation_execution_unchanged'] is True and seed['native_or_preparation_launched'] is False
         and seed['cache_path'] == str(cache) and seed['input_plan']['config'] == plan['config']
         and seed['input_plan']['products'] == plan['products'], 'Cache staging attribution differs')
    need(products['schema'] == 'orbit-poc-five-day-precise-product-preflight-v1'
         and products['status'] == 'passed' and products['product_count'] == 20
         and len(products['records']) == len(seed['products']) == 20, 'Five-day product inventory differs')
    original = {row['name']: row for row in products['records']}
    need(len(original) == 20, 'Duplicate product names')
    cached = []
    for row in seed['products']:
        destination = Path(row['destination']['path']); item = original.get(destination.name)
        need(item is not None and destination == cache/'gnss'/item['name']
             and row['source'] == {'path': item['path'], 'sha256': item['sha256']}
             and row['destination']['sha256'] == item['sha256']
             and row['bytes'] == item['bytes'] and destination.is_file() and not destination.is_symlink()
             and destination.stat().st_size == item['bytes'] and sha(destination) == item['sha256'], 'Cached product bytes or attribution differ')
        cached.append(row['destination'])
    need(len({x['path'] for x in cached}) == 20
         and {x.name for x in (cache/'gnss').iterdir()} == set(original)|{name+'.source.json' for name in original}, 'Cache membership differs')
    readonly = [source, Path(cfg.preparation.auxiliary_dir), Path(cfg.preparation.example_directory)]
    need(all(x.is_dir() and access(x, os.R_OK) and not access(x, os.W_OK) for x in readonly), 'Scientific source or auxiliary/example directory is missing or writable')
    context = validation.execution_context(cfg, root, source)
    gates = validation.require_passed(cfg, context, root, source)
    need(gates['status'] == 'passed', 'Prescribed validation no longer passes')
    flights = protocol.flight_sources(cfg, source)
    expected = {x['case_id'] for x in protocol.planned_cases() if x['stage'] == 'flight'}
    need(len(flights) == len(expected) == 4 and set(flights) == expected, 'Four exact original flight cases required')
    # Exercise the actual frozen cache-reuse prerequisites before any propagation.
    # Exact original acquisition sidecars are preserved; no download is allowed.
    if auxiliary_reuse is None or flight_reuse is None or cached_fetch is None:
        from orbit_poc.comparison.data import fetch_example_auxiliary, fetch_url
        from orbit_poc.comparison.groops_config import fetch_flight_auxiliary
        auxiliary_reuse = auxiliary_reuse or fetch_example_auxiliary
        flight_reuse = flight_reuse or fetch_flight_auxiliary
        cached_fetch = cached_fetch or fetch_url
    auxiliary = auxiliary_reuse(cfg.preparation.example_directory, cfg.preparation.auxiliary_dir, download=False)
    flight_auxiliary = flight_reuse(cfg.preparation.auxiliary_dir, download=False)
    need(auxiliary.get('status') == flight_auxiliary.get('status') == 'complete'
         and len(auxiliary['sources']) == 56 and len(flight_auxiliary['sources']) == 33, 'Complete frozen auxiliary acquisition closure differs')
    prerequisite_records = []
    for item in products['records']:
        path = cache/'gnss'/item['name']
        verified = cached_fetch(item['url'], path, expected_sha256=item['sha256'], download=False)
        need(verified['path'] == str(path) and verified['url'] == item['url']
             and verified['sha256'] == item['sha256'] and verified['bytes'] == item['bytes'], 'Precise-product reuse attribution differs')
        prerequisite_records.append(pin(path.with_name(path.name+'.source.json')))
    interpreter = Path(cfg.preparation.tudat_python)
    need(interpreter.is_absolute() and interpreter.is_file() and access(interpreter, os.X_OK)
         and sha(interpreter) == cfg.preparation.tudat_python_sha256, 'Tudat interpreter differs')
    script = source/'scripts/tudat_truth.py'; need(script.is_file(), 'Frozen truth script is missing')
    # Inherit exactly the preparation environment, like frozen simulator.generate.
    # A different LD_LIBRARY_PATH/PYTHONPATH could conceal a real import failure.
    done = run([str(interpreter), '-c', TUDAT_CODE, str(script)], cwd=source,
               capture_output=True, text=True, timeout=180, check=False)
    need(done.returncode == 0, 'Tudat startup failed: '+done.stderr[-6000:])
    try:
        imported = json.loads(done.stdout)
    except ValueError as ex:
        raise ValueError('Tudat startup did not return its exact structured result') from ex
    need(imported.get('schema') == 'orbit-poc-tudat-startup-v1' and imported.get('status') == 'passed'
         and imported.get('propagations') == 0 and imported.get('truth_script_loaded_without_run') is True
         and len(imported.get('imports', [])) == 5, 'Tudat startup result differs')
    need([x.get('role') for x in imported['imports']] == ['tudatpy', 'environment_setup', 'propagation_setup', 'simulator', 'spice'], 'Tudat import roles differ')
    need(imported['imports'][0].get('file') is not None, 'Tudat package origin is missing')
    for row in imported['imports']:
        need(set(row) == {'role', 'name', 'file'} and isinstance(row['name'], str), 'Unexpected Tudat import identity')
        file = row['file']
        if file is not None:
            need(set(file) == {'path', 'sha256'} and Path(file['path']).is_absolute()
                 and sha(file['path']) == file['sha256'], 'Imported Tudat module changed')
    checked(plan['config']); checked(plan['cache_seed']); checked(plan['products'])
    return {'schema': 'orbit-poc-preparation-startup-result-v1', 'status': 'passed',
            'config': plan['config'], 'source_sha256': plan['source_sha256'],
            'validation_context_hash': context['validation_context_hash'], 'validation': gates,
            'readonly_directories': [str(x) for x in readonly], 'cache_products': cached,
            'flight_sources': {key: value['reference'] for key, value in flights.items()},
            'actual_cache_reuse': {'example_sources': len(auxiliary['sources']), 'flight_sources': len(flight_auxiliary['sources']), 'product_source_records': prerequisite_records, 'network_download_allowed': False},
            'tudat_interpreter': pin(interpreter), 'truth_script': pin(script), 'tudat_startup': imported,
            'tudat_stderr': done.stderr, 'physical_propagations': 0, 'benchmark_fits': 0,
            'scope': 'Startup, existing-input and dependency verification only; no preparation generation, numerical gate or fit.'}


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('--plan', type=Path, required=True); ap.add_argument('--sha256', required=True)
    args = ap.parse_args(argv); need(sha(args.plan) == args.sha256, 'Startup plan changed')
    plan = json.loads(args.plan.read_text()); need(set(plan) == KEYS, 'Unknown startup plan')
    out = Path(plan['output']); need(out.is_absolute() and not out.exists() and not out.is_symlink(), 'Preserve previous startup evidence')
    out.mkdir(parents=True)
    try:
        from orbit_poc.segmented import protocol, validation
        from orbit_poc.segmented.config import load_config
        result = inspect(plan, protocol, validation, load_config)
    except BaseException as ex:
        result = {'schema': 'orbit-poc-preparation-startup-result-v1', 'status': 'failed',
                  'error': repr(ex), 'plan': pin(args.plan), 'physical_propagations': 0, 'benchmark_fits': 0}
    with (out/'result.json').open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps(result, sort_keys=True)); return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
