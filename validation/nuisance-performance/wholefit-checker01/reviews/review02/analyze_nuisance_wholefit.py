#!/usr/bin/env python3
"""Read-only cache-off/on whole-fit outcome and scientific-equality analysis.

Execution outcomes are distinct from full-fit scientific equivalence. A genuine
planned timeout is retained, not converted into a missing-output failure or an
accepted posterior. This tool never executes a native process.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib.abc
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('_wholefit_profile_tools', HERE / 'check_nuisance_performance_pair.py')
profile_tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile_tools)
analysis = profile_tools.analysis
POINT = re.compile(r'point-(\d+)-(.+)')
GEN = re.compile(r'qr\.(\d+)\.(.+)')
DIGEST = re.compile(r'[0-9a-f]{64}')
TERMINAL = analysis.TERMINAL
LIMITS = {'maximum_accepted_iterations': 32, 'maximum_trial_evaluations': 96,
          'wall_time_seconds': 7200., 'initial_damping': 1e-3, 'minimum_gain_ratio': 1e-4,
          'maximum_position_change_m': 3e-5, 'maximum_density_update': 1e-4,
          'maximum_pulse_update_m_s': 1e-8, 'normalized_gradient_tolerance': 1e-8}
RESOURCE_FIELDS = {'elapsed_seconds', 'child_user_seconds', 'child_system_seconds',
                   'peak_child_rss_bytes', 'peak_rss_bytes', 'peak_process_tree_rss_bytes'}
SUCCESS_ROLES = {'state_estimate', 'physical_parameters', 'native_nuisance_profile',
                 'native_initial_state_design', 'native_reference_parameters', 'native_fit_configuration',
                 'native_variational', 'native_qr_factor', 'native_qr_rhs', 'native_qr_coordinates',
                 'native_qr_diagnostics', 'native_objective', 'native_qr_parameters',
                 'native_qr_row_provenance', 'native_qr_row_compression_receipt',
                 'native_preprocessing_audit', 'native_parameter_covariance', 'estimated_orbit_native',
                 'native_parameters', 'phase_recovery', 'full_native_solution', 'native_parameter_names',
                 'cross_segment_covariance', 'selected_dynamic_covariance',
                 'segmented_predictions', 'segmented_prediction_policy'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def stable_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class Evidence:
    """Stable streaming fingerprints: large row spools are never read into RAM."""
    def __init__(self):
        self.records = {}
        self.gate_modules = {}

    def fingerprint(self, path, *, unpack=False):
        path = Path(path).resolve(strict=True)
        before = stable_identity(path)
        digest, count = hashlib.sha256(), 0
        opener = gzip.open if unpack else open
        with opener(path, 'rb') as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                count += len(block)
        if stable_identity(path) != before:
            raise ValueError('Evidence changed while reading: ' + str(path))
        key = (str(path), bool(unpack))
        entry = {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': count,
                 'uncompressed': bool(unpack)}
        if key in self.records and self.records[key][0] != before:
            raise ValueError('Evidence changed between reads: ' + str(path))
        self.records[key] = (before, entry)
        return entry

    def data(self, path, *, limit=16 * 1024 * 1024):
        path = Path(path)
        if path.stat().st_size > limit:
            raise ValueError('Oversize structured receipt: ' + str(path))
        pin = self.fingerprint(path)
        value = path.read_bytes()
        if hashlib.sha256(value).hexdigest() != pin['sha256']:
            raise ValueError('Receipt changed between reads: ' + str(path))
        return value

    def json(self, path):
        value = profile_tools.strict_json(self.data(path))
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object: ' + str(path))
        return value

    def verify(self, item):
        if not isinstance(item, dict) or not DIGEST.fullmatch(str(item.get('sha256', ''))):
            raise ValueError('Missing artifact identity')
        pin = self.fingerprint(item['path'])
        if pin['sha256'] != item['sha256'] or ('bytes' in item and pin['bytes'] != item['bytes']):
            raise ValueError('Artifact identity mismatch: ' + str(item.get('path')))
        return Path(pin['path'])

    def unchanged(self):
        for (path, _), (identity, _) in self.records.items():
            if stable_identity(Path(path)) != identity:
                raise ValueError('Evidence changed during analysis: ' + path)

    def inventory(self):
        return [entry for _, entry in sorted(self.records.values(), key=lambda x:(x[1]['path'], x[1]['uncompressed']))]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def classify_profile(value):
    require(value.get('threshold_m') == 1e-8 and value.get('required_consecutive_small_updates') == 2,
            'Nuisance thresholds changed')
    require(value.get('fixed_weights') is True and value.get('dynamic_updates') is False,
            'Nuisance profile changed weights or physical updates')
    history, iterations = value.get('history'), value.get('iterations')
    require(type(iterations) is int and iterations > 0 and isinstance(history, list)
            and len(history) == iterations and all(isinstance(x, dict) for x in history),
            'Nuisance history/iteration count is invalid')
    require(value.get('maximum_update_m') == history[-1].get('maximum_update_m'),
            'Nuisance final update/history mismatch')
    classification = profile_tools.classify_profile(value)
    if classification == 'strict_nuisance_convergence':
        require(len(history) >= 2 and all(finite(x.get('maximum_update_m'))
                and 0 <= x['maximum_update_m'] < 1e-8 for x in history[-2:]),
                'Strict nuisance status lacks two small updates')
    elif classification == 'floor_limited_progress_only':
        require(profile_tools.valid_floor_receipt(value), 'Invalid nuisance floor audit')
    else:
        raise ValueError('Invalid completed nuisance profile status')
    return classification


def normalize_json(value, name, root):
    """Only declared resource fields and the one exact spool path can change."""
    value = json.loads(json.dumps(value, allow_nan=False))
    if name.endswith('.nuisance_line_search.json'):
        for trial in value.get('trials', []):
            for key in profile_tools.STRIPPED_TRIAL_FIELDS:
                trial.pop(key, None)
    if name.endswith('.factor.json'):
        directory = value.get('spool_directory')
        require(directory == str(root / 'row-spool'), 'Unexpected row spool path')
        value['spool_directory'] = '<run-root>/row-spool'
    # No recursive name-based dropping: an objective/threshold field is scientific.
    return value


def payload(evidence, path):
    return evidence.fingerprint(path, unpack=path.name.endswith('.gz'))


def require_matrix(evidence, path, rows, columns):
    pin = evidence.fingerprint(path)
    require(type(rows) is int and rows > 0 and type(columns) is int and columns > 0,
            'Invalid matrix dimensions')
    require(pin['bytes'] == 16 + 8 * rows * columns, 'Truncated matrix payload')
    with Path(path).open('rb') as stream:
        require(struct.unpack('<QQ', stream.read(16)) == (rows, columns), 'Matrix header mismatch')
        while block := stream.read(1024 * 1024):
            require(len(block) % 8 == 0 and all(math.isfinite(x[0]) for x in struct.iter_unpack('<d', block)),
                    'Nonfinite matrix payload')


def factor_release_inventory(evidence, root):
    path = root / 'factor-retention.json'
    if not path.exists():
        return {}
    value = evidence.json(path)
    require(value.get('policy') == 'released_factor_retention_v1', 'Unexpected factor retention policy')
    result = {}
    for event in value.get('events', []):
        for item in event.get('removed', []):
            absolute = Path(item['path'])
            require(absolute.is_absolute() and absolute.is_relative_to(root), 'Released factor path leaves run')
            if item.get('status') != 'deleted':
                continue
            require(DIGEST.fullmatch(str(item.get('sha256', ''))) and type(item.get('bytes')) is int,
                    'Released factor lacks identity')
            rel = str(absolute.relative_to(root))
            require(rel not in result or result[rel] == item, 'Conflicting factor release identity')
            result[rel] = item
    return result


def inspect_point(evidence, root, point, cache, released, *, allow_partial=False):
    summary = {'name': point.name, 'profile_complete': False, 'classification': 'unfinished_or_unrecorded',
               'issues': [], 'performance': None, 'scientific': {}, 'released_factors': {},
               'profile_elapsed_seconds': None, 'physical_identity': {}, 'incomplete_records': []}
    def problem(message): summary['issues'].append(str(message))
    for name in ['physical_initial.txt', 'fixed_force.txt', 'full_pulses_um_s.txt']:
        path = point / name
        if path.exists(): summary['physical_identity'][name] = payload(evidence, path)
    closure = point / 'closure.json'
    if closure.exists():
        try:
            summary['closure'] = evidence.json(closure)
        except (ValueError,EOFError) as error:
            if not allow_partial: raise
            summary['incomplete_records'].append({'file':closure.name,'reason':str(error)})
    execution = point / 'profile.execution.json'
    complete_command = False
    if execution.exists():
        try:
            command = evidence.json(execution)
        except (ValueError,EOFError) as error:
            if not allow_partial: raise
            summary['incomplete_records'].append({'file':execution.name,'reason':str(error)})
            command = None
        if command is None:
            return summary
        summary['profile_elapsed_seconds'] = command.get('elapsed_seconds')
        require(summary['profile_elapsed_seconds'] is None or finite(summary['profile_elapsed_seconds'])
                and summary['profile_elapsed_seconds'] >= 0, 'Invalid profile elapsed time')
        argv = command.get('command')
        require(isinstance(argv, list) and len(argv) == 2 and Path(argv[1]) == point / 'profile.xml',
                'Native profile command does not identify its configuration')
        require(evidence.fingerprint(point/'profile.xml')['sha256'] == command.get('config_sha256'),
                'Native profile configuration changed')
        complete_command = (type(command.get('returncode')) is int and command['returncode'] == 0
                            and command.get('timed_out') is False)
        summary['profile_execution'] = command
    profile = point / 'qr.profile.json'
    if profile.exists():
        try:
            value = evidence.json(profile)
            summary['classification'] = classify_profile(value)
            summary['profile_complete'] = complete_command
            summary['profile'] = value
            require(summary.get('closure', {}).get('converged') is True, 'Profile lacks completed physical closure')
        except (ValueError,EOFError) as error:
            if complete_command or not allow_partial: raise
            summary['incomplete_records'].append({'file':profile.name,'reason':str(error)})
    elif complete_command:
        raise ValueError('Successful profile process lacks its nuisance summary')
    for name in ['profile.xml','closure.json']:
        path = point/name
        if not path.exists(): continue
        if name.endswith('.xml'):
            try:
                tree = ET.fromstring(evidence.data(path))
            except ET.ParseError as error:
                if complete_command or not allow_partial: raise ValueError(str(error)) from error
                summary['incomplete_records'].append({'file':name,'reason':str(error)})
                continue
            for node in tree.iter():
                if node.text and node.text.startswith(str(root)+'/'):
                    node.text = '<run-root>/'+node.text[len(str(root))+1:]
            data = ET.tostring(tree)
        else:
            if 'closure' not in summary:
                continue
            data = json.dumps(summary['closure'],sort_keys=True,separators=(',',':')).encode()
        summary['scientific'][name] = {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'kind':'declared_output_path_normalized' if name.endswith('.xml') else 'exact_json'}
    # Every present scientific receipt is retained, even after a failed native command.
    for path in sorted(point.iterdir()):
        if not path.is_file(): continue
        name = profile_tools.scientific_name(path)
        if name is None: continue
        if path.name.endswith(profile_tools.JSON_SUFFIXES):
            try:
                value = normalize_json(evidence.json(path), name, root)
            except (ValueError,EOFError) as error:
                if complete_command or not allow_partial: raise
                summary['incomplete_records'].append({'file':path.name,'reason':str(error)})
                continue
            data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            item = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'kind': 'canonical_scientific_json'}
        else:
            item = {k:v for k,v in payload(evidence,path).items() if k in ('sha256','bytes')}
            item['kind'] = 'uncompressed_bytes'
        require(name not in summary['scientific'] or summary['scientific'][name] == item,
                'Conflicting raw/compressed scientific artifact')
        summary['scientific'][name] = item
        if path.name.endswith('.rows.tsv.gz'):
            receipt_path = path.with_name(path.name[:-3] + '.compression.json')
            receipt = evidence.json(receipt_path)
            require(receipt.get('round_trip_verified') is True
                    and receipt.get('source', {}).get('sha256') == item['sha256']
                    and receipt.get('source', {}).get('bytes') == item['bytes'],
                    'Compressed row provenance lacks verified source identity')
            evidence.verify(receipt['compressed'])
    for path in sorted(point.glob('qr.*.retention.json')):
        try:
            receipt = evidence.json(path)
        except (ValueError,EOFError) as error:
            if complete_command or not allow_partial: raise
            summary['incomplete_records'].append({'file':path.name,'reason':str(error)})
            continue
        if receipt.get('status') != 'completed' and not complete_command and allow_partial:
            summary['incomplete_records'].append({'file':path.name,'reason':'native release interrupted'})
            continue
        require(receipt.get('schema') == 'orbit-poc-native-factor-retention-v1'
                and receipt.get('status') == 'completed', 'Incomplete native factor retention receipt')
        for item in receipt.get('artifacts', []):
            absolute = Path(item['path'])
            require(absolute.parent == point and absolute.name in {path.name.removesuffix('.retention.json')+suffix
                    for suffix in ('.R.bin','.rhs.bin','.z.bin')}, 'Unexpected native released artifact')
            require(DIGEST.fullmatch(str(item.get('sha256',''))) and type(item.get('bytes')) is int
                    and item['bytes'] >= 16, 'Released native artifact lacks identity')
            summary['released_factors'][absolute.name] = {k:item[k] for k in ('sha256','bytes')}
    for rel, item in released.items():
        if Path(rel).parent == Path(point.name):
            summary['released_factors'][Path(rel).name] = {k:item[k] for k in ('sha256','bytes')}
    searches, sidecars = {}, []
    for path in sorted(point.glob('qr.*.nuisance_line_search.json')):
        try:
            searches[int(path.name.split('.')[1])] = evidence.json(path)
        except (ValueError,EOFError) as error:
            if complete_command or not allow_partial: raise
            summary['incomplete_records'].append({'file':path.name,'reason':str(error)})
    for path in sorted(point.glob('qr.*.nuisance_performance.json')):
        number = int(path.name.split('.')[1])
        if number not in searches and allow_partial and not complete_command:
            summary['incomplete_records'].append({'file':path.name,'reason':'no completed canonical search'})
            continue
        require(number in searches, 'Performance sidecar lacks canonical search')
        try:
            value = evidence.json(path)
        except (ValueError,EOFError) as error:
            if complete_command or not allow_partial: raise
            summary['incomplete_records'].append({'file':path.name,'reason':str(error)})
            continue
        analysis.validate_performance(value, searches[number])
        parent = value['parent_row_build']
        child_rows = [value['zero_update_replay']['row_build'],
            *(c['row_build'] for c in value['ordinary_trials']),
            *(c['row_build'] for c in value['arithmetic_audits']),
            *(c['row_build'] for group in value['probe_rounds'] for c in group)]
        for row in child_rows:
            if row.get('available') is not True: continue
            require(type(row.get('interpolation_cache')) is bool and row['interpolation_cache'] == bool(cache),
                    'Child native cache treatment mismatch')
            require(all(type(row.get(k)) is int and row[k] >= 0 for k in ['interpolation_calls','interpolation_cache_hits','interpolation_evaluations'])
                    and row['interpolation_calls'] == row['interpolation_cache_hits'] + row['interpolation_evaluations'],
                    'Inconsistent child interpolation counters')
            require(cache or row['interpolation_cache_hits'] == 0, 'Cache-off child reports cache hits')
        require(type(parent.get('interpolation_cache')) is bool and parent['interpolation_cache'] == bool(cache),
                'Native sidecar cache treatment mismatch')
        for key in ('interpolation_calls','interpolation_cache_hits','interpolation_evaluations'):
            require(type(parent.get(key)) is int and parent[key] >= 0, 'Invalid interpolation counter')
        require(parent['interpolation_calls'] == parent['interpolation_cache_hits'] + parent['interpolation_evaluations'],
                'Inconsistent interpolation counters')
        require(cache or parent['interpolation_cache_hits'] == 0, 'Cache-off run reports cache hits')
        sidecars.append(value)
    summary['performance'] = analysis.performance_summary(sidecars)
    summary['sidecar_count'] = len(sidecars)
    if summary['profile_complete']:
        iterations = summary['profile']['iterations']; final = iterations + 1
        require(set(searches) == set(range(1, iterations+1)), 'Completed profile has missing/extra search generations')
        require(len(sidecars) == iterations, 'Completed profile lacks complete performance sidecar coverage')
        names = summary['scientific']
        generations = {int(m[1]) for n in names if (m := GEN.fullmatch(n))}
        require(generations == set(range(1, final+1)), 'Completed scientific generations are not contiguous')
        for i in range(1, final+1):
            for suffix in profile_tools.REQUIRED_FACTOR:
                name = f'qr.{i}.{suffix}'
                if suffix in ('R.bin','rhs.bin') and name in summary['released_factors']:
                    # Native/adapter release proofs are distinct from available payloads.
                    continue
                require(name in names, 'Completed profile missing scientific artifact: ' + name)
        diag = evidence.json(point / f'qr.{final}.diagnostics.json')
        require(type(diag.get('lambda')) in (int,float) and diag['lambda'] == 0 and diag.get('rank_status') == 'full',
                'Final nuisance linearization is not fresh undamped/full rank')
        require(f'qr.{final}.nuisance_line_search.json' not in names, 'Final factor reused a search generation')
        summary['final_generation'] = final
        summary['fresh_undamped_full_rank'] = True
    return summary


def compare_points(left, right):
    """Partial-prefix evidence never certifies complete-fit equivalence."""
    output = []
    for name in sorted(set(left) | set(right)):
        a, b = left.get(name), right.get(name)
        item = {'name':name, 'status':'unmatched_progress', 'scientific_comparisons':[], 'issues':[]}
        if a is None or b is None:
            item['present_cache'] = 0 if a is not None else 1
            output.append(item); continue
        keys = {'physical_initial.txt','fixed_force.txt','full_pulses_um_s.txt'}
        def identity(point): return {k:(v['sha256'],v['bytes']) for k,v in point['physical_identity'].items()}
        if set(a['physical_identity']) != keys or identity(a) != identity(b):
            item.update(status='physical_inputs_differ_or_incomplete')
            output.append(item); continue
        names = set(a['scientific']) | set(b['scientific']) | set(a['released_factors']) | set(b['released_factors'])
        complete = a['profile_complete'] and b['profile_complete']
        for artifact in sorted(names):
            x, y = a['scientific'].get(artifact), b['scientific'].get(artifact)
            # A factor released by the declared policy has a separate evidence class.
            if x is None: x = a['released_factors'].get(artifact)
            if y is None: y = b['released_factors'].get(artifact)
            if x is None or y is None:
                if complete: item['issues'].append('Unmatched complete-point artifact: '+artifact)
                continue
            equal = x['sha256'] == y['sha256'] and x['bytes'] == y['bytes']
            item['scientific_comparisons'].append({'artifact':artifact,'equal':equal,
                'left_sha256':x['sha256'],'right_sha256':y['sha256'],
                'scope':'direct bytes/values' if artifact in a['scientific'] and artifact in b['scientific'] else 'recorded pre-release identity'})
            if not equal: item['issues'].append('Scientific artifact differs: '+artifact)
        item.update(status='different' if item['issues'] else 'equal_completed_point' if complete else 'equal_available_prefix',
                    both_profiles_complete=complete)
        output.append(item)
    return output


@contextmanager
def frozen_gates(evidence, freeze, pinned):
    """Load verified source bytes without mutable modules or bytecode caches."""
    base = Path(freeze['source_root'])/'src'
    require(evidence.fingerprint(Path(sys.executable).resolve())['sha256'] == freeze['python']['sha256'],
            'Scientific gates require the frozen Python interpreter')
    class FrozenLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != 'orbit_poc' and not fullname.startswith('orbit_poc.'):
                return None
            candidate = base.joinpath(*fullname.split('.'))
            package = candidate/'__init__.py'
            file = package if package.is_file() else candidate.with_suffix('.py')
            require(file.is_file(), 'Frozen scientific module missing: '+fullname)
            return importlib.util.spec_from_file_location(fullname,file,loader=self,
                submodule_search_locations=[str(file.parent)] if file == package else None)
        def create_module(self, spec): return None
        def exec_module(self, module):
            file = Path(module.__spec__.origin).resolve()
            require(str(file) in pinned, 'Scientific module omitted from frozen pins: '+str(file))
            raw = evidence.data(file)
            require(hashlib.sha256(raw).hexdigest() == pinned[str(file)],
                    'Frozen scientific module bytes changed: '+str(file))
            evidence.gate_modules[module.__name__] = {'path':str(file), 'sha256':pinned[str(file)]}
            exec(compile(raw,str(file),'exec',dont_inherit=True),module.__dict__)
    saved = {k:v for k,v in sys.modules.items() if k == 'orbit_poc' or k.startswith('orbit_poc.')}
    for key in saved: del sys.modules[key]
    loader = FrozenLoader(); sys.meta_path.insert(0,loader)
    try:
        from orbit_poc.segmented import report
        yield report  # Remain active through lazy imports performed by the gate.
    finally:
        sys.meta_path.remove(loader)
        for key in list(sys.modules):
            if key == 'orbit_poc' or key.startswith('orbit_poc.'): del sys.modules[key]
        sys.modules.update(saved)


def validate_optimizer_record(evidence, root, worker):
    value = evidence.json(root/'iterations.json')
    keys = {'status','converged','accepted_iterations','trial_evaluations','objective_floor',
            'history','confirmation_checks','elapsed_seconds'}
    require(set(value) == keys, 'Complete optimizer record has missing/unknown fields')
    require(all(value[k] == worker.get(k) for k in keys-{'elapsed_seconds'}),
            'Optimizer record is stale or differs from its worker result')
    require(value['status'] == 'complete' and value['converged'] is True,
            'Optimizer record is not a complete fit')
    require(type(value['accepted_iterations']) is int and 0 <= value['accepted_iterations'] <= 32
            and type(value['trial_evaluations']) is int and 0 <= value['trial_evaluations'] <= 96,
            'Optimizer counters violate frozen controls')
    history, checks = value['history'], value['confirmation_checks']
    require(isinstance(history,list) and history and isinstance(checks,list) and checks
            and all(isinstance(x,dict) for x in history+checks), 'Missing optimizer confirmation evidence')
    trials = [x for x in history if 'trial' in x]
    require([x['trial'] for x in trials] == list(range(1,value['trial_evaluations']+1))
            and sum(x.get('accepted') is True for x in trials) == value['accepted_iterations'],
            'Optimizer counters/history disagree')
    require(history[-1].get('confirmation') is True and history[-1].get('accepted') is True
            and checks[-1].get('stationary') is True and checks[-1].get('nuisance_floor_limited') is False
            and checks[-1].get('physical_parameters_unchanged') is True,
            'Complete optimizer lacks its final strict confirmation')
    require(finite(value['objective_floor']) and value['objective_floor'] >= 0
            and worker.get('objective_resolution') == value['objective_floor'], 'Optimizer measured objective floor differs')
    return value


def validate_point_inventory(evidence, root, worker, points):
    runtime = evidence.json(root/'native_runtime.json')
    require(runtime == worker.get('runtime'), 'Native runtime differs from worker result')
    executions = runtime.get('execution')
    require(isinstance(executions,list) and executions, 'Complete fit lacks native execution ledger')
    expected = set()
    for record in executions:
        argv = record.get('command')
        require(isinstance(argv,list) and len(argv) == 2, 'Invalid native execution ledger command')
        path = Path(argv[1])
        require(path.is_relative_to(root), 'Native execution configuration leaves isolated fit')
        rel = path.relative_to(root)
        if not POINT.fullmatch(rel.parts[0]): continue
        expected.add(rel.parts[0])
        require(evidence.fingerprint(path)['sha256'] == record.get('config_sha256')
                and evidence.json(path.with_suffix('.execution.json')) == record,
                'Native execution ledger differs from retained command receipt')
    require(expected == set(points), 'Full-fit point inventory differs from its native execution ledger')
    ordered = sorted(expected,key=lambda name:int(POINT.fullmatch(name)[1]))
    require(len(ordered) >= 5 and [int(POINT.fullmatch(name)[1]) for name in ordered] == list(range(1,len(ordered)+1)),
            'Complete fit lacks a contiguous physical evaluation sequence')
    require(ordered[:3] == ['point-001-initial','point-002-repeat','point-003-closure-refinement']
            and ordered[-2].endswith('-confirmation') and ordered[-1].endswith('-final-covariance'),
            'Complete fit lacks initial floor measurements or final confirmation/covariance')
    return ordered


def validate_success(evidence, result, job, root, points, freeze, pinned):
    """Use existing strict gates; do not silently accept a partial final posterior."""
    with frozen_gates(evidence,freeze,pinned) as gates:
        gates.strict_result(result,job)
    validate_optimizer_record(evidence,root,result)
    validate_point_inventory(evidence,root,result,points)
    items = result.get('artifacts', [])
    by_role = {}
    for item in items:
        path = evidence.verify(item)
        require(path.is_relative_to(root), 'Result artifact leaves isolated run')
        by_role.setdefault(item['role'], []).append(item)
    require(all(len(by_role.get(role,[])) == 1 for role in SUCCESS_ROLES), 'Missing/duplicate required full-fit artifact')
    profile_path = Path(by_role['native_nuisance_profile'][0]['path'])
    require(profile_path.parent.name.endswith('-final-covariance'), 'Final result does not identify final-covariance point')
    final = points.get(profile_path.parent.name)
    require(final and final['profile_complete'] and final['classification'] == 'strict_nuisance_convergence'
            and final.get('fresh_undamped_full_rank') is True, 'Final covariance lacks strict fresh nuisance linearization')
    final_gen = final['final_generation']
    for role,suffix in [('native_qr_factor','R.bin'),('native_qr_rhs','rhs.bin'),
                        ('native_qr_coordinates','factor.json'),('native_qr_diagnostics','diagnostics.json'),
                        ('native_objective','profile.json'),('native_qr_parameters','parameters.tsv')]:
        require(Path(by_role[role][0]['path']) == profile_path.parent/f'qr.{final_gen}.{suffix}',
                'Final artifact references a stale factor: '+role)
    factor = evidence.json(profile_path.parent/f'qr.{final_gen}.factor.json')
    require(factor.get('rows') == factor.get('columns'), 'Final factor is not square')
    require_matrix(evidence, profile_path.parent/f'qr.{final_gen}.R.bin',factor['rows'],factor['columns'])
    require_matrix(evidence, profile_path.parent/f'qr.{final_gen}.rhs.bin',factor['rows'],1)
    objective = evidence.json(profile_path.parent/f'qr.{final_gen}.profile.json')
    require(finite(result.get('objective')) and result['objective'] == objective.get('direct_cost'),
            'Result objective differs from fresh actual objective')
    require(finite(result.get('objective_resolution')) and result['objective_resolution'] >= 0,
            'Measured objective floor missing')
    require(result.get('source_hash') == job.get('source_hash'), 'Result source identity changed')
    require(result.get('preprocessing_hash') == job.get('preprocessing_hash')
            and result.get('mask_hash') == job.get('mask_hash'), 'Result preprocessing/mask identity changed')
    return by_role


def compare_success(evidence, a, b, freeze, pinned):
    import numpy as np
    with frozen_gates(evidence,freeze,pinned) as module:
        gates = module.equivalence(a['worker'],b['worker'])
    differences = []
    for key in ['optimizer_record']:
        x,y = ({k:v for k,v in run[key].items() if k != 'elapsed_seconds'} for run in (a,b))
        if x != y: differences.append(key)
    for role in ['state_estimate','physical_parameters','cross_segment_covariance','selected_dynamic_covariance',
                 'segmented_predictions','native_preprocessing_audit','native_qr_factor','native_qr_rhs']:
        x,y = (Path(run['success_artifacts'][role][0]['path']) for run in (a,b))
        if x.suffix == '.npz':
            with np.load(x,allow_pickle=False) as left, np.load(y,allow_pickle=False) as right:
                equal = set(left.files) == set(right.files) and all(left[k].dtype == right[k].dtype
                    and left[k].shape == right[k].shape and np.array_equal(left[k],right[k]) for k in left.files)
        elif x.suffix == '.json':
            equal = evidence.json(x) == evidence.json(y)
        else:
            equal = payload(evidence,x)['sha256'] == payload(evidence,y)['sha256']
        if not equal: differences.append(role)
    return {'status':'passed' if gates['status'] == 'passed' and not differences else 'failed',
            'existing_v4_gates':gates,'exact_result_differences':differences,
            'scope':'Same candidate/cache-only arithmetic test. Any scientific difference remains a failure even within existing v4 tolerances.'}


def verify_freeze(evidence, root):
    freeze_path = root/'freeze.json'
    freeze = evidence.json(freeze_path)
    freeze_sha = evidence.fingerprint(freeze_path)['sha256']
    require(freeze.get('schema') == 'orbit-poc-nuisance-wholefit-freeze-v1', 'Unknown whole-fit freeze schema')
    require(Path(freeze.get('root','')).resolve() == root, 'Freeze root mismatch')
    jobs = freeze.get('jobs')
    require(isinstance(jobs,list) and len(jobs) == 2 and {j.get('cache') for j in jobs} == {0,1}
            and all(type(j.get('cache')) is int and j.get('name') == 'cache'+str(j['cache']) for j in jobs),
            'Freeze must retain exactly cache0 and cache1')
    require(freeze.get('wall_time_seconds') == 7200 and freeze.get('maximum_process_tree_rss_bytes') == 8*1024**3,
            'Frozen whole-fit limits changed')
    require(type(freeze.get('cpu')) is int and freeze['cpu'] >= 0, 'Missing frozen CPU')
    environment = freeze.get('environment')
    require(isinstance(environment,dict) and environment.get('ORBIT_POC_NUISANCE_PERFORMANCE') == '1'
            and {k for k in environment if k.startswith('ORBIT_POC_')} == {'ORBIT_POC_NUISANCE_PERFORMANCE'},
            'Freeze contains unknown/missing numerical environment controls')
    for key in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:
        require(environment.get(key) == '1', 'One-thread control missing: '+key)
    pins = freeze.get('pinned_files')
    require(isinstance(pins,list) and pins, 'Missing frozen source/input/runtime pins')
    pinned = {}
    for item in pins:
        path = str(evidence.verify(item))
        require(path not in pinned or pinned[path] == item['sha256'], 'Conflicting frozen pins')
        pinned[path] = item['sha256']
    for key in ['python','worker','runner']:
        path = evidence.verify(freeze[key])
        require(pinned.get(str(path)) == freeze[key]['sha256'], 'Unpinned execution control: '+key)
    requests = {}
    for job in jobs:
        path = evidence.verify(job['request'])
        require(pinned.get(str(path)) == job['request']['sha256'], 'Request omitted from frozen pin inventory')
        request = evidence.json(path)
        require(request.get('method') == 'groops_pulses' and request.get('segmented_profile') == 'dense_corrected'
                and request.get('numerics_profile') == 'qr_lm_staged_jacobian', 'Unexpected whole-fit scientific profile')
        controls = request.get('numerical_controls', {})
        require(isinstance(controls,dict) and set(controls) <= set(LIMITS)
                and all(type(v) in (int,float) and v == LIMITS[k] for k,v in controls.items()),
                'Numerical controls changed')
        native = Path(request['backend']['groops_executable']).resolve()
        require(pinned.get(str(native)) == request.get('expected_native_binary_sha256'), 'Native identity not frozen')
        require(request.get('source_hash') == freeze.get('source_hash'), 'Request source differs from freeze')
        require(type(request.get('nuisance_performance_cache')) is int
                and request['nuisance_performance_cache'] == job['cache'], 'Request cache identity differs')
        expected_job_sha = hashlib.sha256(json.dumps({k:v for k,v in request.items() if k != 'job_sha256'},
            sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        require(request.get('job_sha256') == expected_job_sha and job.get('job_sha256') == expected_job_sha,
                'Canonical job hash mismatch')
        require(isinstance(request.get('id'),str) and request['id'].startswith('nuisance-wholefit-cache'+str(job['cache'])+'--'),
                'Request identifier differs from treatment')
        requests[job['cache']] = request
    ignored = {'id','job_sha256','nuisance_performance_cache'}
    require({k:v for k,v in requests[0].items() if k not in ignored}
            == {k:v for k,v in requests[1].items() if k not in ignored},
            'Cache pair requests differ in inputs or scientific controls')
    return freeze, freeze_sha, requests, pinned


def inspect_run(evidence, experiment, freeze, freeze_sha, planned, job, pinned):
    root = experiment/planned['name']; cache = planned['cache']
    output = {'name':planned['name'],'cache':cache,'outcome':'not_started','analysis_status':'pending',
              'scientific_complete':False,'accepted_covariance':False,'issues':[], 'points':{},
              'wall_seconds':None,'peak_process_tree_rss_bytes':None,'worker':None,
              'cache_treatment_verified':False,'cache_hit_coverage':'unknown'}
    if not root.exists(): return output
    result_path = root/'result.json'
    if not result_path.exists():
        output['outcome'] = 'started_without_terminal_result'
        return output  # Never inspect a live/uncertain point tree.
    result = evidence.json(result_path)
    require(result.get('cache') == cache and type(result.get('cache')) is int
            and result.get('freeze_sha256') == freeze_sha
            and result.get('request_sha256') == planned['request']['sha256'], 'Terminal result attribution mismatch')
    records = result.get('evidence')
    require(isinstance(records,dict), 'Terminal result lacks evidence ledger')
    expected_files = {'request':'request.json','supervisor':'supervisor.json',
                      'worker_result':'worker-result.json','effective_environment':'effective-environment.json'}
    for key,name in expected_files.items():
        path = root/name
        if records.get(key) is None:
            require(not path.exists(), 'Unpinned existing execution evidence: '+key)
        else:
            require(Path(records[key]['path']) == path, 'Execution receipt path mismatch: '+key)
            evidence.verify(records[key])
    require(records.get('request') and records.get('supervisor'), 'Missing mandatory execution evidence')
    require(evidence.fingerprint(root/'request.json')['sha256'] == planned['request']['sha256']
            and evidence.json(root/'request.json') == job, 'Executed request differs from freeze')
    supervisor = evidence.json(root/'supervisor.json')
    require(result.get('harness_execution') == supervisor, 'Terminal and supervisor evidence disagree')
    require(supervisor.get('status') in TERMINAL and supervisor.get('status') != 'running', 'Supervisor is not terminal')
    require(supervisor.get('owned_process_group_cleaned') is True
            and supervisor.get('cleanup',{}).get('verified') is True, 'Owned cleanup not verified')
    plan = evidence.json(root/'supervisor.plan.json')
    require(supervisor.get('plan_sha256') == evidence.fingerprint(root/'supervisor.plan.json')['sha256'],
            'Supervisor plan hash mismatch')
    expected_argv = [freeze['python']['path'],'-s','-B',freeze['worker']['path'],freeze['source_root'],
                     str(root/'request.json'),str(root/'worker-result.json'),str(cache),
                     str(experiment/'freeze.json'),freeze_sha]
    require(supervisor.get('argv') == expected_argv and plan.get('argv') == expected_argv,
            'Supervisor argv is not the frozen direct-worker command')
    helper_path = str((Path(freeze['source_root'])/'src/orbit_poc/segmented/supervisor.py').resolve())
    require(DIGEST.fullmatch(str(pinned.get(helper_path,'')))
            and supervisor.get('helper_sha256') == pinned[helper_path]
            and plan.get('helper_sha256') == pinned[helper_path], 'Supervisor helper is not frozen')
    require(supervisor.get('boot_id') == freeze['boot_id'] and plan.get('boot_id') == freeze['boot_id'],
            'Supervisor boot identity mismatch')
    require(plan.get('timeout_seconds') == 7200 and plan.get('max_process_tree_rss_bytes') == 8*1024**3
            and plan.get('min_free_disk_bytes') == freeze['minimum_free_output_bytes']
            and plan.get('cwd') == freeze['source_root'] and plan.get('working_directory') == str(root),
            'Supervisor limits or working roots differ')
    post = evidence.json(root/'post-input-check.json')
    require(post.get('verified') is True and post.get('freeze_sha256') == freeze_sha
            and post.get('pinned_file_count') == len(freeze['pinned_files']), 'Post-fit identity check missing/failed')
    if records.get('effective_environment'):
        env = evidence.json(root/'effective-environment.json')
        expected_env = {**freeze['environment'],'ORBIT_POC_NUISANCE_INTERPOLATION_CACHE':str(cache)}
        require(env.get('schema') == 'orbit-poc-nuisance-wholefit-environment-v1'
                and env.get('cache') == cache and type(env.get('cache')) is int
                and env.get('environment') == expected_env and env.get('cpu_affinity') == [freeze['cpu']]
                and env.get('freeze_sha256') == freeze_sha and env.get('request_sha256') == planned['request']['sha256']
                and env.get('source') == freeze['source_root'] and env.get('boot_id') == freeze['boot_id']
                and type(env.get('pid')) is int and env['pid'] == supervisor.get('worker',{}).get('pid'),
                'Effective worker environment/treatment identity mismatch')
        output['cache_treatment_verified'] = True
    worker = evidence.json(root/'worker-result.json') if records.get('worker_result') else None
    outer = supervisor['status']
    require(type(supervisor.get('returncode')) is int, 'Terminal supervisor return code missing')
    if outer in {'timeout','memory_limit','disk_limit','interrupted'}:
        require(result.get('status') == outer and result.get('converged') is False
                and result.get('covariance_valid') is False, 'Resource/interruption outcome was upgraded to success')
    elif supervisor['returncode'] != 0 or worker is None:
        require(result.get('status') == 'failed' and result.get('converged') is False
                and result.get('covariance_valid') is False, 'Failed/missing worker upgraded to success')
    else:
        additions = {'freeze_sha256','cache','request_sha256','harness_execution','evidence'}
        if result.get('reported_worker_status') == 'complete' and result.get('status') == 'failed':
            require(worker.get('status') == 'complete' and result.get('converged') is False
                    and result.get('covariance_valid') is False
                    and str(result.get('error','')).startswith('Complete worker receipt failed the existing strict gate: '),
                    'Invalid strict-gate rejection attribution')
            rejected = False
            with frozen_gates(evidence,freeze,pinned) as gates:
                try: gates.strict_result(worker,job)
                except (ValueError,KeyError,TypeError,OSError): rejected = True
            require(rejected, 'Controller rejected a valid strict result without supporting evidence')
        else:
            require({k:v for k,v in result.items() if k not in additions} == worker,
                    'Controller altered the scientific worker result')
    require(result.get('status') in TERMINAL, 'Unknown terminal fit status')
    if result.get('status') != 'complete':
        require(result.get('converged') is False and result.get('covariance_valid') is False,
                'Failed result claims convergence or accepted covariance')
    output.update(outcome=result['status'],analysis_status='valid',worker=worker,
                  wall_seconds=supervisor.get('elapsed_seconds'),
                  peak_process_tree_rss_bytes=supervisor.get('peak_process_tree_rss_bytes'))
    require(finite(output['wall_seconds']) and output['wall_seconds'] >= 0
            and type(output['peak_process_tree_rss_bytes']) is int and output['peak_process_tree_rss_bytes'] >= 0,
            'Invalid outer resource metrics')
    released = factor_release_inventory(evidence,root)
    for point in sorted(root.iterdir()):
        if point.is_dir() and POINT.fullmatch(point.name):
            try:
                item = inspect_point(evidence,root,point,cache,released,allow_partial=result['status'] != 'complete')
                if item.get('profile_execution'):
                    require(item['profile_execution'].get('native_binary_sha256') == job['expected_native_binary_sha256']
                            and Path(item['profile_execution']['command'][0]).resolve() == Path(job['backend']['groops_executable']).resolve()
                            and item['profile_execution'].get('blas_openmp_threads') == 1,
                            'Native profile binary or threads differ from freeze')
                output['points'][point.name] = item
            except (OSError,ValueError,KeyError,TypeError,EOFError) as error:
                output['points'][point.name] = {'name':point.name,'issues':[str(error)],'profile_complete':False,
                    'physical_identity':{},'scientific':{},'released_factors':{}}
                output['issues'].append(point.name+': '+str(error))
    known = [p for p in output['points'].values() if p.get('performance')]
    hits = [p['performance']['parent_row_build']['interpolation_cache_hits']['recorded_sum'] for p in known]
    if any(x is not None for x in hits):
        count = sum(x for x in hits if x is not None)
        output['recorded_parent_cache_hits'] = count
        output['cache_hit_coverage'] = 'positive_native_hits' if count > 0 else 'recorded_zero_hits'
        if cache and result['status'] == 'complete': require(count > 0, 'Completed cache-on run never exercised cache')
    output['recorded_profile_wall_seconds'] = sum(p['profile_elapsed_seconds'] for p in output['points'].values()
        if finite(p.get('profile_elapsed_seconds'))) if any(finite(p.get('profile_elapsed_seconds')) for p in output['points'].values()) else None
    output['profile_wall_coverage'] = {'planned_or_started_points':len(output['points']),
        'recorded_profile_commands':sum(finite(p.get('profile_elapsed_seconds')) for p in output['points'].values()),
        'completed_nuisance_profiles':sum(p.get('profile_complete',False) for p in output['points'].values()),
        'scope':'Recorded command wall only; a timed-out command may be included, and absent command receipts remain unknown.'}
    if result['status'] == 'complete':
        require((root/'iterations.json').is_file(), 'Complete fit lacks optimizer record')
        require(output['cache_treatment_verified'], 'Complete run lacks actual worker environment')
        output['success_artifacts'] = validate_success(evidence,worker,job,root,output['points'],freeze,pinned)
        output['scientific_complete'] = True
        output['accepted_covariance'] = True
    iterations = root/'iterations.json'
    if iterations.exists():
        output['optimizer_record'] = evidence.json(iterations)
    runtime = root/'native_runtime.json'
    if runtime.exists():
        record = evidence.json(runtime)
        output['runtime_summary'] = {k:record.get(k) for k in ['propagation_count','accepted_iterations',
            'trial_evaluations','elapsed_seconds','peak_rss_bytes','peak_rss_scope','native_binary_sha256','derivative_profile']}
    return output


def analyze(root):
    root = Path(root).resolve(strict=True)
    evidence = Evidence()
    report = {'schema':'orbit-poc-nuisance-wholefit-analysis-v1',
              'created_at':datetime.now(timezone.utc).isoformat(), 'root':str(root),
              'analysis_status':'invalid','scientific_equivalence':{'status':'not_evaluable'},
              'whole_fit_complete_pair':False,'release_authority':False,'issues':[], 'runs':[],
              'planned_attempts':2,'partial_point_comparisons':[],
              'scope':'Two separately frozen full fits; failures/timeouts are outcomes, never replacement campaign results.',
              'limitations':['One observation per treatment; no statistical speedup or accuracy-superiority claim.',
                'Whole-fit covariance acceptance requires strict final convergence; floor-limited profiles are progress only.',
                'Nested sidecar wall/CPU measurements are not an exhaustive total and must not be added.',
                'A valid outcome analysis can contain two timeouts; it is not a scientific equivalence pass.']}
    try:
        freeze, freeze_sha, requests, pinned = verify_freeze(evidence,root)
        report['freeze_sha256'] = freeze_sha
        report['execution_order'] = [j['name'] for j in freeze['jobs']]
        for planned in freeze['jobs']:
            try:
                run = inspect_run(evidence,root,freeze,freeze_sha,planned,requests[planned['cache']],pinned)
            except (OSError,ValueError,TypeError,KeyError,EOFError) as error:
                run = {'name':planned['name'],'cache':planned['cache'],'analysis_status':'invalid',
                       'outcome':'invalid_evidence','issues':[str(error)],'points':{},'scientific_complete':False,
                       'accepted_covariance':False}
            report['runs'].append(run)
        runs = {r['cache']:r for r in report['runs']}
        for run in report['runs']:
            report['issues'].extend(run['name']+': '+issue for issue in run.get('issues',[]))
        report['partial_point_comparisons'] = compare_points(runs[0]['points'],runs[1]['points'])
        differences = [p for p in report['partial_point_comparisons'] if p['status'] == 'different'
            or p['status'] in ('physical_inputs_differ_or_incomplete','unmatched_progress')
            and all(r['scientific_complete'] for r in runs.values())]
        if all(r['scientific_complete'] for r in runs.values()) and not report['issues']:
            report['whole_fit_complete_pair'] = True
            report['scientific_equivalence'] = compare_success(evidence,runs[0],runs[1],freeze,pinned)
            if differences:
                report['scientific_equivalence']['status'] = 'failed'
                report['scientific_equivalence']['different_point_count'] = len(differences)
        elif differences:
            report['scientific_equivalence'] = {'status':'failed_available_prefix',
                'different_point_count':len(differences),'full_fit_evaluated':False}
        report['analysis_status'] = ('invalid' if report['issues'] else 'pending'
            if any(r['analysis_status'] == 'pending' for r in runs.values()) else 'valid')
        report['outcome_comparison'] = {'cache_off':runs[0]['outcome'],'cache_on':runs[1]['outcome'],
            'whole_fit_time_ratio':None,'timing_scope':'Censored or failed fits do not yield a completed-fit speed ratio.'}
        if report['whole_fit_complete_pair']:
            report['outcome_comparison']['whole_fit_time_ratio'] = runs[0]['wall_seconds']/runs[1]['wall_seconds']
            report['outcome_comparison']['timing_scope'] = 'Single observed cache-off/cache-on wall ratio; no uncertainty estimate.'
        for run in report['runs']:
            # Large real backend results remain separately pinned; expose selected fields and artifact identities.
            worker = run.pop('worker',None)
            if worker is not None:
                run['worker_summary'] = {k:worker.get(k) for k in ['status','numerical_status','converged','covariance_valid',
                    'objective','objective_resolution','strict_nuisance_converged','strict_final_correction',
                    'accepted_iterations','trial_evaluations','preprocessing_audit_sha256','force_model_hash',
                    'measurement_model_hash','preprocessing_hash','mask_hash','source_hash','native_binary_sha256']}
            run.pop('success_artifacts',None)
        evidence.unchanged()
    except (OSError,ValueError,TypeError,KeyError,EOFError) as error:
        report['issues'].append(str(error))
        report['analysis_status'] = 'invalid'
        report['scientific_equivalence'] = {'status':'not_evaluable'}
        report['whole_fit_complete_pair'] = False
    report['scientific_gate_modules'] = dict(sorted(evidence.gate_modules.items()))
    report['evidence'] = evidence.inventory()
    report['tool'] = evidence.fingerprint(Path(__file__))
    report['dependencies'] = [evidence.fingerprint(HERE/name) for name in
                              ['analyze_nuisance_profile.py','check_nuisance_performance_pair.py']]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    if args.output.exists(): raise SystemExit('Refusing to overwrite an analysis receipt')
    result = analyze(args.root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['analysis_status','scientific_equivalence','whole_fit_complete_pair']}))
    return 0 if result['analysis_status'] == 'valid' else 2


if __name__ == '__main__':
    raise SystemExit(main())
