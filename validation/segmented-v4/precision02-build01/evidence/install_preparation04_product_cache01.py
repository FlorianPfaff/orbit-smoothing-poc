"""Install exact product copies only after the fresh14-gate independent audit."""
from pathlib import Path
import argparse, hashlib, json, shutil

STAGES = ('native-tests', 'correction-tests', 'synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses', 'flight-refinement', 'eccentric-24h-refinement', 'objective-log_drag_ou', 'objective-pulses', 'nuisance-replay', 'nuisance-replay-candidate1-point012', 'segmented-native-tangent', 'segmented-structural', 'linearization-log_drag_ou', 'linearization-pulses')

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p): return {'path': str(p), 'sha256': sha(p)}
def require(ok, why):
    if not ok: raise ValueError(why)
def canonical(p):
    p = Path(p)
    require(p.is_absolute() and str(p) == str(p.resolve()), 'Canonical path without symlink ancestors required')
    return p
def checked(x):
    require(isinstance(x, dict) and {'path', 'sha256'} <= set(x) <= {'path', 'sha256', 'bytes'}, 'Invalid pin')
    p = canonical(x['path'])
    require(p.is_file() and sha(p) == x['sha256'], 'Pinned artifact changed')
    if 'bytes' in x: require(p.stat().st_size == x['bytes'], 'Pinned artifact size changed')
    return p
def read(x): return json.loads(checked(x).read_text())
def same(a, b): return a['path'] == b['path'] and a['sha256'] == b['sha256']

def install(staging_pin, controller_pin, audit_pin, receipt):
    receipt = canonical(receipt)
    require(not receipt.exists() and not receipt.is_symlink() and receipt.parent.is_dir(), 'Fresh receipt required')
    s, c, audit = read(staging_pin), read(controller_pin), read(audit_pin)
    e = read(s['execution']); cache = canonical(e['paths']['build'])
    require(Path(controller_pin['path']) == Path(e['paths']['control'])/'validation-controller.json', 'Wrong validation controller path')
    require(c['status'] == 'passed' and c['final_cleanup']['verified'] is True and c['final_cleanup']['errors'] == [], 'Fresh validation is not clean and passed')
    cp = read(c['plan'])
    require(cp['execution'] == s['execution'], 'Validation execution differs from cache staging')
    p = read(c['cli_validation']['pipeline'])
    require(p['status'] == 'passed' and tuple(x['name'] for x in p['steps']) == STAGES and all(x['status'] == 'passed' for x in p['steps']), 'All original14 gates must pass')
    require(audit.get('schema') == 'orbit-poc-segmented-validation-terminal-independent-review-v1' and audit.get('consistency_passed') is True and audit.get('scientific_status') == 'passed_scoped_checks' and audit.get('cleanup_verified') is True, 'Independent terminal audit must pass')
    for key in ('controller', 'cli_pipeline', 'validation_context', 'validation_plan', 'run_plan', 'config', 'source_freeze', 'launch_plan', 'launch_pins'):
        checked(audit['artifacts'][key])
    for key, expected in (('controller', controller_pin), ('cli_pipeline', c['cli_validation']['pipeline']), ('config', cp['config']), ('source_freeze', cp['source_freeze']), ('launch_plan', c['plan'])):
        require(same(audit['artifacts'][key], expected), 'Independent audit attribution differs: '+key)
    freeze, config = read(cp['source_freeze']), read(cp['config'])
    ident = audit['identity']
    require(ident['full_source_sha256'] == freeze['source']['sha256'] and ident['comparison_source_sha256'] == freeze['comparison_source']['sha256'] == config['segmented_runtime']['source_sha256'] == config['dense_runtime']['source_sha256'], 'Independent source identity differs')
    require(ident['native_sha256'] == config['segmented_runtime']['native']['sha256'] and ident['solver_sha256'] == config['segmented_runtime']['segmented_solver']['sha256'], 'Independent native identity differs')
    require(str(cache) == config['preparation']['cache_dir'], 'Canonical preparation cache differs')
    require(cache.is_dir() and not any(cache.iterdir()), 'Fresh empty preparation cache required')
    rows = s['entries']
    require(s['product_count'] == 20 and s['record_count'] == 20 and len(rows) == 20 and s['network_requests'] == 0, 'Wrong cache inventory')
    names = []
    for row in rows:
        product, record = checked(row['copied_product']), checked(row['copied_record'])
        require(record.name == product.name+'.source.json' and product.name.endswith('.gz'), 'Wrong product/record pair')
        names.extend((product.name, record.name))
    require(len(set(names)) == 40, 'Duplicate cache filenames')
    target = cache/'gnss'; target.mkdir(); out = []
    for row in rows:
        saved = {}
        for key in ('copied_product', 'copied_record'):
            old = checked(row[key]); new = target/old.name
            with old.open('rb') as src, new.open('xb') as dst: shutil.copyfileobj(src, dst)
            require(sha(new) == row[key]['sha256'] and (new.stat().st_dev, new.stat().st_ino) != (old.stat().st_dev, old.stat().st_ino), 'Cache copy/inode differs')
            saved[key] = pin(new)
        out.append({'staged_source': row, 'installed': saved})
    result = {'schema': 'orbit-poc-preparation04-product-cache-install-v1', 'staging': staging_pin, 'validation_controller': controller_pin, 'validation_pipeline': c['cli_validation']['pipeline'], 'independent_terminal_audit': audit_pin, 'cache': str(cache), 'entries': out, 'network_requests': 0, 'native_propagations': 0, 'metadata_scope': 'Preserved byte-identical earlier offline verification records, not new acquisition receipts. No earlier prefix, initialization or failed scientific output copied.'}
    with receipt.open('x') as stream: json.dump(result, stream, indent=2); stream.write('\n')
    return pin(receipt)

def main(argv=None):
    parser = argparse.ArgumentParser()
    for key in ('staging', 'controller', 'audit'):
        parser.add_argument('--'+key, type=Path, required=True); parser.add_argument('--'+key+'-sha256', required=True)
    parser.add_argument('--receipt', type=Path, required=True); args = parser.parse_args(argv)
    pins = [dict(path=str(getattr(args, key)), sha256=getattr(args, key+'_sha256')) for key in ('staging', 'controller', 'audit')]
    print(json.dumps(install(*pins, args.receipt)))
if __name__ == '__main__': main()
