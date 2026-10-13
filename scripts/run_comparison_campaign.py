"""Run the gated v3 campaign in order, freezing all test inputs before fitting.

This driver is included in the scientific runtime source snapshot. It uses
the runtime's blind preparation API and separately pins its own bytes in the
input freeze. It never manufactures acceptance evidence or forwards references to fit.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def launch_resources(requested_workers, meminfo_path=Path('/proc/meminfo')):
    """Conservative launch budget, not a claim that peak RSS is bounded."""
    values = {}
    for line in Path(meminfo_path).read_text().splitlines():
        words = line.split()
        if words[0] in ('MemTotal:', 'MemAvailable:'):
            values[words[0][:-1]] = int(words[1])*1024
    if set(values) != {'MemTotal', 'MemAvailable'}:
        raise RuntimeError('Cannot establish launch-time available memory from /proc/meminfo')
    reserve, per_worker = 8*1024**3, int(3.5*1024**3)
    capacity = max(0, (values['MemAvailable']-reserve)//per_worker)
    chosen = min(requested_workers, capacity)
    if chosen < 1:
        raise RuntimeError('Insufficient available memory: need at least 11.5 GiB '
                           '(8 GiB reserve plus 3.5 GiB per native worker)')
    return {'observed_at': timestamp(), 'available_bytes': values['MemAvailable'],
            'total_bytes': values['MemTotal'], 'reserve_bytes': reserve,
            'planning_budget_per_worker_bytes': per_worker, 'requested_workers': requested_workers,
            'chosen_workers': chosen, 'estimated_worker_budget_bytes': chosen*per_worker,
            'available_after_estimated_worker_budget_bytes': values['MemAvailable']-chosen*per_worker,
            'policy': 'Cap each launch by available memory, reserving 8 GiB and budgeting 3.5 GiB per worker; this estimate is not a hard RSS limit'}


def evaluation_cases(config, stage):
    """Exactly the case expansion used by protocol.run, including secondary arms."""
    from orbit_poc.comparison.protocol import case_matrix
    primary = case_matrix(config, stage, 'evaluation')
    if stage == 'synthetic':
        secondary = [{**case, 'seed': 500000 + case['seed'] - config.synthetic.evaluation_seeds[0],
                      'truth_model': 'tudat_mixed_force_stress_gnss'}
                     for case in primary if case['orbit'] == 'leo500'
                     and case['atmosphere'] == 'disturbed'
                     and case['seed'] in config.synthetic.evaluation_seeds[:5]]
        return {'primary': primary, 'stress': secondary}
    return {'primary': primary,
            'flight_ar_reference': [{**case, 'ambiguity_policy': 'integer'}
                                    for case in primary if case['coverage'] == 'normal']}


def input_inventory(prepared):
    """Hash declarations for raw/derived inputs, plus protected native inputs.

    Reference files are only hashed; their contents are not interpreted here.
    Only the prepared native-input manifest JSON is traversed.
    """
    from orbit_poc.comparison.protocol import file_hash, read_json
    records = []
    for group in ('estimation_inputs', 'evaluation_inputs', 'calibration_inputs', 'artifacts'):
        for item in prepared.get(group, []):
            path = str(Path(item['path']).resolve())
            if file_hash(path) != item['sha256']:
                raise ValueError('Prepared input changed before evaluation freeze: ' + path)
            records.append({'usage': group, 'role': item['role'], 'path': path,
                            'sha256': item['sha256']})
            if item.get('metadata', {}).get('kind') == 'native_preparation':
                for native in read_json(path).get('native_artifacts', []):
                    native_path = str(Path(native['path']).resolve())
                    if file_hash(native_path) != native['sha256']:
                        raise ValueError('Converted input changed before evaluation freeze: ' + native_path)
                    records.append({'usage': 'converted_estimation_inputs', 'role': native['role'],
                                    'path': native_path, 'sha256': native['sha256']})
    acquisition = Path(prepared['record_path']).parent / 'observations' / 'data_manifest.json'
    if acquisition.is_file():
        records.append({'usage': 'provenance', 'role': 'acquisition_generation_manifest',
                        'path': str(acquisition.resolve()), 'sha256': file_hash(acquisition)})
    return records


def verify_input_freeze(record, config, frozen, selection, stage):
    from orbit_poc.comparison.protocol import canonical_hash, file_hash, read_json, read_result_record
    payload = {key: value for key, value in record.items() if key != 'input_freeze_hash'}
    if record.get('input_freeze_hash') != canonical_hash(payload):
        raise ValueError('Evaluation input freeze has been modified')
    expected = {'protocol_hash': frozen['protocol_hash'], 'source_hash': frozen['source']['sha256'],
                'selection_hash': selection['selection_hash'], 'native_binary': frozen['native_binary'],
                'driver_sha256': file_hash(__file__), 'stage': stage}
    for key, value in expected.items():
        if record.get(key) != value:
            raise ValueError('Evaluation input freeze identity changed: ' + key)
    planned = [{'campaign': campaign, 'case': case}
               for campaign, cases in evaluation_cases(config, stage).items() for case in cases]
    actual = [{'campaign': item['campaign'], 'case': item['case']} for item in record['prepare_results']]
    if actual != planned:
        raise ValueError('Evaluation input freeze does not contain every planned case exactly once')
    declared = {(item['usage'], item['role'], item['path'], item['sha256']) for item in record['inputs']}
    observed = set()
    slr_dates = set()
    for entry in record['prepare_results']:
        if file_hash(entry['index_path']) != entry['index_sha256']:
            raise ValueError('A prepared result index changed after evaluation freeze')
        prepared = read_result_record(entry['result_record'])
        if prepared['status'] not in ('prepared', 'excluded'):
            raise ValueError('Evaluation input freeze includes an unprepared case')
        observed.update((item['usage'], item['role'], item['path'], item['sha256'])
                        for item in input_inventory(prepared))
        if stage == 'flight' and prepared['status'] == 'prepared':
            slr_dates.add(entry['case']['date'])
    from orbit_poc.comparison.slr import verify_slr_auxiliary, slr_auxiliary_inventory
    correction_entries = record.get('slr_auxiliary', [])
    if len(correction_entries) != len(slr_dates) or {item['date'] for item in correction_entries} != slr_dates:
        raise ValueError('Evaluation freeze lacks date-specific SLR corrections')
    for item in correction_entries:
        if file_hash(item['path']) != item['sha256']:
            raise ValueError('Frozen SLR correction manifest changed')
        correction = read_json(item['path'])
        verify_slr_auxiliary(correction, item['date'], correction['crd_source']['path'],
                             config.backend.auxiliary_dir)
        observed.update((row['usage'], row['role'], row['path'], row['sha256'])
                        for row in slr_auxiliary_inventory(item['path'], correction))
    if observed != declared:
        raise ValueError('Evaluation input freeze inventory is incomplete or inconsistent')
    return record


def prepared_cases(runner, frozen, stage, split, planned):
    """Prime each date serially, then prepare private case directories in parallel.

    The first case fills public-download and native-transmitter caches. Subsequent
    cases only reuse those verified inputs; native transmitter conversion also
    has its own advisory lock. Yield in planned order, regardless of completion
    order, so concurrency cannot change a frozen input inventory.
    """
    from orbit_poc.comparison.protocol import _prepared
    def prepare_one(item):
        index, campaign, case = item
        result = _prepared(runner, frozen, stage, split, case, split == 'evaluation')
        return index, campaign, case, result
    indexed = [(index, campaign, case) for index, (campaign, case) in enumerate(planned)]
    primes, dates = {}, set()
    for item in indexed:
        date = item[2].get('date', item[2].get('epoch', 'common'))
        if date not in dates:
            primes[item[0]] = prepare_one(item)
            dates.add(date)
    remaining = iter(runner.map(prepare_one, [item for item in indexed if item[0] not in primes]))
    for item in indexed:
        result = primes[item[0]] if item[0] in primes else next(remaining)
        if result[0] != item[0]:
            raise ValueError('Preparation results changed the planned case order')
        yield result[1:]


def prepare_calibration_inputs(config, root, frozen, stage, workers, budget_hours=168):
    from orbit_poc.comparison.protocol import Runner, case_matrix, result_record, write_json
    runner = Runner(root, workers=workers, budget_hours=budget_hours, resume=True)
    planned = [('calibration', case) for case in case_matrix(config, stage, 'calibration')]
    records = []
    path = root / ('calibration-input-preparation-' + stage + '.json')
    for _, case, prepared in prepared_cases(runner, frozen, stage, 'calibration', planned):
        records.append({'case': case, 'result_record': result_record(prepared)})
        write_json(path, {'stage': stage, 'protocol_hash': frozen['protocol_hash'],
            'status': 'prepared' if len(records) == len(planned) else 'preparing',
            'workers': workers, 'prepared_cases': len(records), 'expected_cases': len(planned),
            'prepare_results': records})
    return {'path': str(path), 'prepared_cases': len(records), 'workers': workers}


def freeze_evaluation_inputs(config, root, frozen, stage, budget_hours=168, workers=1):
    from orbit_poc.comparison.protocol import (Runner, _selection, canonical_hash,
        file_hash, read_json, result_record, write_json)
    selection = _selection(config, root, frozen, stage)
    path = root / ('evaluation-input-freeze-' + stage + '.json')
    if path.exists():
        return verify_input_freeze(read_json(path), config, frozen, selection, stage)
    campaigns = evaluation_cases(config, stage)
    runner = Runner(root, workers=workers, budget_hours=budget_hours, resume=True)
    entries, inventory, slr_auxiliary = [], {}, {}
    progress = root / ('evaluation-input-preparation-' + stage + '.json')
    planned = [(campaign, case) for campaign, cases in campaigns.items() for case in cases]
    for campaign, case, prepared in prepared_cases(runner, frozen, stage, 'evaluation', planned):
        index = result_record(prepared)
        index_path = Path(prepared['record_path']).with_name('result-record.json')
        entries.append({'campaign': campaign, 'case': case, 'result_record': index,
                        'index_path': str(index_path), 'index_sha256': file_hash(index_path)})
        inputs = input_inventory(prepared)
        if stage == 'flight' and prepared['status'] == 'prepared':
            from orbit_poc.comparison.slr import preflight_slr_auxiliary, slr_auxiliary_inventory
            date = case['date']
            crd = [item for item in prepared.get('evaluation_inputs', []) if item['role'] == 'slr_validation']
            if len(crd) != 1:
                raise ValueError('Flight evaluation freeze requires exactly one SLR source per date')
            correction_path = root / 'slr-auxiliary-freeze' / (date + '.json')
            correction = preflight_slr_auxiliary(date, crd[0]['path'], config.backend.auxiliary_dir,
                correction_path, allow_frozen_evaluation=True)
            entry = {'date': date, 'path': str(correction_path.resolve()),
                     'sha256': file_hash(correction_path)}
            if date in slr_auxiliary and slr_auxiliary[date] != entry:
                raise ValueError('SLR corrections changed between evaluation preparations')
            slr_auxiliary[date] = entry
            inputs += slr_auxiliary_inventory(correction_path, correction)
        for item in inputs:
            key = (item['usage'], item['role'], item['path'])
            if key in inventory and inventory[key]['sha256'] != item['sha256']:
                raise ValueError('An input changed between evaluation preparations')
            inventory[key] = item
        write_json(progress, {'stage': stage, 'protocol_hash': frozen['protocol_hash'],
            'selection_hash': selection['selection_hash'], 'status': 'preparing',
            'prepared_cases': len(entries), 'expected_cases': sum(map(len, campaigns.values())),
            'prepare_results': entries})
    record = {'schema_version': 1, 'stage': stage, 'status': 'frozen', 'completed_at': timestamp(),
              'protocol_hash': frozen['protocol_hash'], 'selection_hash': selection['selection_hash'],
              'source_hash': frozen['source']['sha256'], 'native_binary': frozen['native_binary'],
              'driver_sha256': file_hash(__file__),
              'campaign_case_counts': {name: len(cases) for name, cases in campaigns.items()},
              'prepare_results': entries, 'inputs': [inventory[key] for key in sorted(inventory)],
              'slr_auxiliary': [slr_auxiliary[date] for date in sorted(slr_auxiliary)],
              'reference_policy': 'Evaluation inputs are prepared and hashed only after calibration freezes; SLR station headers locate correction sources, while normal-point values and GNV remain uninterpreted until evaluation; no references or SLR enter estimators',
              'excluded_cases': sum(row['result_record']['status'] == 'excluded' for row in entries)}
    record['input_freeze_hash'] = canonical_hash(record)
    verify_input_freeze(record, config, frozen, selection, stage)
    write_json(path, record)
    write_json(progress, {'stage': stage, 'protocol_hash': frozen['protocol_hash'], 'status': 'frozen',
                         'input_freeze_path': str(path), 'input_freeze_hash': record['input_freeze_hash'],
                         'prepared_cases': len(entries)})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--synthetic-workers', type=int, default=24)
    parser.add_argument('--flight-workers', type=int, default=24)
    args = parser.parse_args()
    from orbit_poc.comparison.config import load_config
    from orbit_poc.comparison.protocol import freeze_protocol, read_json, write_json
    from orbit_poc.comparison.gates import validate_gates
    if not all(1 <= n <= 24 for n in (args.synthetic_workers, args.flight_workers)):
        parser.error('Requested worker counts must be between 1 and 24')
    config = load_config(args.config)
    root = Path(config.output_dir).resolve()
    frozen = freeze_protocol(config, root)
    validate_gates(root, frozen)

    def stage(name, workers):
        record = {'stage': name, 'protocol_hash': frozen['protocol_hash'],
                  'started_at': timestamp(), 'requested_workers': workers, 'commands': [], 'status': 'running'}
        path = root / ('driver-' + name + '.json')
        def command(action, campaign=None):
            label = '-'.join(x for x in (action, name, campaign) if x)
            argv = [sys.executable, '-m', 'orbit_poc.cli', 'comparison', action,
                    '--config', str(args.config.resolve()), '--stage', name]
            resources = None
            if action != 'report':
                resources = launch_resources(workers)
                argv += ['--workers', str(resources['chosen_workers']), '--budget-hours', '168']
            if campaign:
                argv += ['--campaign', campaign]
            item = {'argv': argv, 'started_at': timestamp(), 'log': str(root / (label + '.log'))}
            if resources is not None: item['launch_resources'] = resources
            record['commands'].append(item)
            write_json(path, record)
            with open(item['log'], 'a') as log:
                result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())
            item.update(returncode=result.returncode, finished_at=timestamp())
            write_json(path, record)
            if result.returncode:
                raise RuntimeError(label + ' failed; see ' + item['log'])
        try:
            preparation_resources = launch_resources(workers)
            record['calibration_preparation_resources'] = preparation_resources
            write_json(path, record)
            record['calibration_input_preparation'] = prepare_calibration_inputs(
                config, root, frozen, name, preparation_resources['chosen_workers'])
            command('calibrate')
            selection = read_json(root / ('calibration-' + name + '.json'))
            if not selection.get('complete'):
                raise RuntimeError('Calibration did not produce a complete frozen selection')
            record['selection_hash'] = selection['selection_hash']
            record['calibration_adequate'] = selection['calibration_adequate']
            preparation_resources = launch_resources(workers)
            record['evaluation_preparation_resources'] = preparation_resources
            write_json(path, record)
            inputs = freeze_evaluation_inputs(config, root, frozen, name,
                                              workers=preparation_resources['chosen_workers'])
            record['evaluation_input_freeze_hash'] = inputs['input_freeze_hash']
            record['evaluation_input_case_counts'] = inputs['campaign_case_counts']
            write_json(path, record)
            for campaign in evaluation_cases(config, name):
                verify_input_freeze(inputs, config, frozen, selection, name)
                command('run', campaign)
                output = name if campaign == 'primary' else campaign
                result = read_json(root / ('run-' + output + '.json'))
                command('report', campaign)
                if not result.get('complete'):
                    raise RuntimeError('Campaign did not attempt all frozen cases: ' + output)
            record['status'] = 'complete'
        except Exception as error:
            record.update(status='failed', error=f'{type(error).__name__}: {error}')
        finally:
            record['finished_at'] = timestamp()
            write_json(path, record)
        return record

    records = []
    for name, workers in (('synthetic', args.synthetic_workers), ('flight', args.flight_workers)):
        records.append(stage(name, workers))
        if records[-1]['status'] != 'complete':
            break
    complete = len(records) == 2 and all(row['status'] == 'complete' for row in records)
    write_json(root / 'campaign-driver.json', {'finished_at': timestamp(), 'stages': records,
        'status': 'complete' if complete else 'failed',
        'interpretation': 'Execution completeness only; scientific validity and unavailable SLR are reported separately'})
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
