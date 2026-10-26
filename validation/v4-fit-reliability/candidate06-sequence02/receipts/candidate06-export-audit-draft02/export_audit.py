"""SOURCE-ONLY UNTESTED draft: saved NPZ/native-export consistency, no authority.

Never run while sequence02 owns admission. This module does not propagate, refit,
alter exports or reconstruct covariance from a tangent operator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

ROOT = Path('/mnt/d/orbit-v41-recovery02/candidate06-cold02')
SOURCE_SHA = '3c9174b52e0b894ffee58f0f4a28bb5e633e5861b377da0a587eac9eb8f2b702'
SOURCE_SNAPSHOT_FILE_SHA = '24c41840ad687aef76111e213b027c8ff613463313ccd7fb8fbf759e253db739'
FROZEN_REQUEST_SHAS = {
    'cold-pulses': '5c7bcf93ea3f31f2eacfcde93191ec72c6c13b210fd74eb21e92eee2aa6ddcd4',
    'cold-density': '64849179436c1fd957bf181fd57d49cb4c3f053899bf08d1bb56edd4aa98c3d7',
}
NATIVE_SHA = '28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
STAGES = ('cold-pulses', 'cold-density')
ARRAYS = ('times', 'mjd', 'states', 'covariance', 'prediction_mjd', 'prediction_covariance')
MAX_BYTES = 256 * 1024 * 1024
MAX_ROWS = 100000


class Unavailable(Exception):
    """Missing saved evidence or unsupported bounded parser resource/format."""


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def pinned(pin, owner=None):
    require(isinstance(pin, dict) and isinstance(pin.get('path'), str), 'Malformed artifact pin')
    require(re.fullmatch('[0-9a-f]{64}', str(pin.get('sha256'))) is not None, 'Malformed SHA256')
    path = Path(pin['path'])
    require(path.is_absolute() and path.resolve() == path, 'Noncanonical artifact path')
    if owner is not None:
        require(path.is_relative_to(owner), 'Artifact escapes declared owner')
    if not path.is_file():
        raise Unavailable('Missing pinned evidence: ' + str(path))
    require(digest(path) == pin['sha256'], 'Artifact hash mismatch: ' + str(path))
    return path


def small_json(path):
    if Path(path).stat().st_size > 16 * 1024 * 1024:
        raise Unavailable('JSON exceeds audit parser resource cap')
    def reject_constant(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), 'Nonfinite/overflow JSON number: ' + value)
        return parsed
    return json.loads(Path(path).read_text(), parse_constant=reject_constant, parse_float=finite_float)


def write_new_json(path, value):
    """Serialize first, then atomically publish without overwriting any report."""
    payload = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode('utf-8')
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.export-audit-', dir=path.parent, delete=False) as f:
            temporary = Path(f.name)
            f.write(payload); f.flush(); os.fsync(f.fileno())
        # Same-filesystem hard link is atomic and refuses an existing target.
        # No replace/non-atomic fallback if this filesystem cannot support it.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def role(result, name):
    entries = [x for x in result.get('artifacts', []) if x.get('role') == name]
    require(len(entries) == 1, 'Missing/nonunique role: ' + name)
    return entries[0]


def bounded_npz(path):
    """Preflight ZIP/NPY headers before NumPy can allocate untrusted shapes."""
    with zipfile.ZipFile(path) as z:
        members = z.infolist()
        expected = {x + '.npy' for x in ARRAYS}
        require(len(members) == len(expected) and {x.filename for x in members} == expected,
                'NPZ has missing, extra or duplicate members')
        if sum(x.file_size for x in members) > MAX_BYTES:
            raise Unavailable('NPZ uncompressed bytes exceed audit resource cap')
        for member in members:
            require(not member.flag_bits & 1 and not member.is_dir(), 'Unsupported ZIP member')
            with z.open(member) as f:
                version = np.lib.format.read_magic(f)
                if version == (1, 0):
                    shape, _, dtype = np.lib.format.read_array_header_1_0(f)
                elif version == (2, 0):
                    shape, _, dtype = np.lib.format.read_array_header_2_0(f)
                else:
                    raise Unavailable('Unsupported NPY version: ' + repr(version))
                require(dtype == np.dtype('float64') and not dtype.hasobject, 'Expected native float64 arrays')
                require(isinstance(shape, tuple) and all(type(n) is int and n >= 0 for n in shape), 'Malformed NPY shape')
                count = math.prod(shape)
                if len(shape) > 3 or count > MAX_BYTES // 8:
                    raise Unavailable('NPY shape exceeds audit resource cap')
                require(f.tell() + 8 * count == member.file_size, 'NPY payload length differs from header')
    with np.load(path, allow_pickle=False) as z:
        return {key: np.array(z[key], copy=True) for key in ARRAYS}


def native_lines(path):
    if Path(path).stat().st_size > MAX_BYTES:
        raise Unavailable('Native text exceeds audit resource cap')
    return [line.split('#', 1)[0].strip() for line in Path(path).read_text().splitlines()
            if line.split('#', 1)[0].strip()]


def floats(lines, width):
    if len(lines) > MAX_ROWS:
        raise Unavailable('Native row count exceeds audit resource cap')
    rows = []
    for line in lines:
        words = line.split()
        require(len(words) == width, 'Truncated/extra native numeric columns')
        rows.append([float(word.replace('D', 'E').replace('d', 'e')) for word in words])
    require(len(rows) > 0, 'Empty native numeric table')
    value = np.asarray(rows, dtype=np.float64)
    require(np.isfinite(value).all(), 'Nonfinite native table')
    return value


def orbit_table(path):
    lines = native_lines(path)
    if not (len(lines) >= 4 and lines[0] == 'groops instrument version=20200123'):
        raise Unavailable('Unsupported orbit header')
    require(lines[1].split() == ['-6', '1'], 'Expected one native ORBIT arc')
    require(re.fullmatch('[0-9]+', lines[2]) is not None, 'Invalid orbit row count')
    count = int(lines[2])
    table = floats(lines[3:], 10)
    require(len(table) == count, 'Orbit declared/actual row count differs')
    ordered(table[:, 0], 'native orbit')
    return table


def covariance_table(path):
    lines = native_lines(path)
    if not (len(lines) >= 3 and lines[0] == 'groops matrix version=20200123'):
        raise Unavailable('Unsupported covariance header')
    match = re.fullmatch(r'Matrix\(\s*([0-9]+)\s*x\s*37\s*\)', lines[1])
    require(match is not None, 'Expected 37-column native covariance matrix')
    table = floats(lines[2:], 37)
    require(len(table) == int(match.group(1)), 'Covariance declared/actual row count differs')
    ordered(table[:, 0], 'native covariance')
    return table


def ordered(epochs, label):
    if epochs.ndim == 1 and len(epochs) > MAX_ROWS:
        raise Unavailable('Epoch count exceeds audit resource cap: ' + label)
    require(epochs.ndim == 1 and len(epochs) > 0 and np.isfinite(epochs).all()
            and np.all(np.diff(epochs) > 0), 'Invalid epoch support: ' + label)


def covariance_valid(covariance, count, label):
    require(covariance.shape == (count, 6, 6) and np.isfinite(covariance).all(), 'Covariance shape/finite: ' + label)
    diagonal = np.diagonal(covariance, axis1=1, axis2=2)
    require(np.all(diagonal > 0), 'Nonpositive covariance diagonal: ' + label)
    require(np.allclose(covariance, covariance.transpose(0, 2, 1), rtol=1e-9, atol=1e-14),
            'Asymmetric covariance under frozen policy: ' + label)
    sd = np.sqrt(diagonal)
    # The unchanged policy checks Cholesky on the supplied matrix. No averaging,
    # clipping, jitter, rescaling of the reported covariance or eigenvalue repair.
    np.linalg.cholesky(covariance / sd[:, :, None] / sd[:, None, :])
    return {'count': count, 'maximum_raw_asymmetry': float(np.max(abs(covariance-covariance.transpose(0, 2, 1))))}


def compare_arrays(arrays, orbit, covariance, prediction):
    require(set(arrays) == set(ARRAYS), 'Array inventory differs')
    require(all(x.dtype == np.dtype('float64') and np.isfinite(x).all() for x in arrays.values()), 'NPZ dtype/finite contract')
    epochs = arrays['mjd']; pred_epochs = arrays['prediction_mjd']
    ordered(epochs, 'NPZ regular'); ordered(pred_epochs, 'NPZ prediction')
    require(arrays['states'].shape == (len(epochs), 6), 'Non-Cartesian states')
    require(arrays['times'].shape == epochs.shape, 'Times shape differs')
    regular_check = covariance_valid(arrays['covariance'], len(epochs), 'NPZ regular')
    prediction_check = covariance_valid(arrays['prediction_covariance'], len(pred_epochs), 'NPZ prediction')
    # These are the very float64 values read to construct the NPZ; equality is
    # exact, not a new orbital accuracy tolerance.
    require(np.array_equal(epochs, orbit[:, 0]), 'NPZ/native orbit epochs differ')
    require(np.array_equal(arrays['states'], orbit[:, 1:7]), 'NPZ/native SI states differ')
    require(np.array_equal(arrays['times'], (epochs-epochs[0])*86400.), 'NPZ elapsed times differ')
    require(len(covariance) == len(epochs) and np.allclose(covariance[:, 0], epochs, rtol=0, atol=1e-9),
            'Native orbit/covariance epoch serialization exceeds unchanged 1e-9 MJD policy')
    require(np.array_equal(arrays['covariance'], covariance[:, 1:].reshape(-1, 6, 6)), 'NPZ/native regular covariance differs')
    require(np.array_equal(pred_epochs, prediction[:, 0]), 'NPZ/native prediction epochs differ')
    require(np.array_equal(arrays['prediction_covariance'], prediction[:, 1:].reshape(-1, 6, 6)), 'NPZ/native prediction covariance differs')
    return {'regular': regular_check, 'prediction': prediction_check, 'npz_native_values_exact': True,
            'maximum_regular_epoch_serialization_difference_mjd': float(np.max(abs(covariance[:, 0]-epochs))),
            'native_binary_decoded': False, 'covariance_reconstructed_from_designs': False}


def xml_paths(path, folder):
    require(path.stat().st_size <= 16*1024*1024, 'XML exceeds audit resource cap')
    document = path.read_bytes()
    require(b'<!DOCTYPE' not in document.upper() and b'<!ENTITY' not in document.upper(), 'XML entity declarations unsupported')
    tree = ET.fromstring(document)
    dynamics = tree.findall('.//GnssProcessing/parametrization/leoDynamicOrbits')
    require(len(dynamics) == 1, 'Expected one LEO dynamic parametrization')
    paths = {}
    for tag in ('outputfileOrbit', 'outputfileOrbitNative', 'outputfileCovariance', 'outputfileCovarianceObservationEpochs'):
        nodes = dynamics[0].findall(tag)
        require(len(nodes) == 1 and nodes[0].text, 'Missing/nonunique XML export: ' + tag)
        value = nodes[0].text.strip()
        require('{' not in value and '}' not in value, 'Unresolved XML filename variables')
        target = Path(value)
        require(target.is_absolute() and target.resolve() == target and target.is_relative_to(folder), 'Foreign/noncanonical final XML export')
        paths[tag] = target
    require(len(set(paths.values())) == 4, 'Aliased final XML exports')
    prefixes = tree.findall('.//GnssProcessing/processingStep/orbitPocNumerics/outputfilePrefix')
    require(len(prefixes) == 1 and prefixes[0].text == str(folder/'qr'), 'XML profile/final folder identity differs')
    require(len(tree.findall('.//GnssProcessing/processingStep/computeCovarianceMatrix')) == 1, 'No unique final covariance step')
    return paths


def audit_stage(entry):
    require(set(entry) == {'stage', 'backend', 'strict', 'exports'}, 'Unknown stage manifest fields')
    stage = entry['stage']; owner = ROOT/stage; fit = owner/'fit'
    result_path = pinned(entry['backend'], owner)
    require(result_path == owner/'backend-result.json', 'Wrong backend result path')
    result = small_json(result_path)
    recorded = {k: result.get(k) for k in ('status', 'numerical_status', 'converged', 'covariance_valid', 'error')}
    if not (result.get('status') == result.get('numerical_status') == 'complete' and result.get('converged') is True and result.get('covariance_valid') is True):
        return {'status': 'not_applicable_unsuccessful_fit', 'backend_outcome': recorded, 'passed': False}
    request_pin = {'path': str(owner/'request.json'), 'sha256': FROZEN_REQUEST_SHAS[stage]}
    request_path = pinned(request_pin, owner)
    request = small_json(request_path)
    require(request['source_hash'] == SOURCE_SHA and result['source_hash'] == request['source_hash']
            and result['native_binary_sha256'] == NATIVE_SHA, 'Wrong candidate/native identity')
    require(result.get('method') == request.get('method'), 'Result differs from frozen request method')
    require(result.get('method') == ('groops_pulses' if stage == 'cold-pulses' else 'groops_log_drag_ou'), 'Method/stage differs')
    strict_path = pinned(entry['strict'], owner)
    require(strict_path == owner/'strict-result.json', 'Wrong strict result path')
    strict = small_json(strict_path)
    require(strict.get('stage') == stage and strict.get('status') == 'passed' and strict.get('accepted_covariance') is True, 'No strict fit covariance outcome')
    estimate = role(result, 'state_estimate'); profile = role(result, 'native_nuisance_profile')
    config = role(result, 'native_fit_configuration'); native = role(result, 'estimated_orbit_native')
    profile_path = pinned(profile, fit); folder = profile_path.parent
    require(folder.name.endswith('-final-covariance') and folder.parent == fit, 'Not one owned final covariance point')
    require(profile_path.name == 'qr.profile.json' and strict['evidence']['final_profile']['path'] == str(profile_path)
            and strict['evidence']['final_profile']['sha256'] == profile['sha256'], 'Strict/final profile mismatch')
    config_path = pinned(config, folder)
    require(config_path == folder/'profile.xml', 'Wrong final XML configuration')
    paths = xml_paths(config_path, folder)
    estimate_path = pinned(estimate, fit)
    require(estimate_path == fit/'fit.npz', 'Wrong Cartesian estimate path')
    selected_paths = [result_path, strict_path, request_path, estimate_path, profile_path, config_path, *paths.values()]
    require(len(selected_paths) == len(set(selected_paths)), 'Final export aliases selected metadata or NPZ path')
    require(pinned(native, folder) == paths['outputfileOrbitNative'], 'Native orbit role/XML disagree')
    exports = entry['exports']
    require(set(exports) == {'orbit', 'covariance', 'prediction_covariance'}, 'Exact ASCII export pin inventory required')
    mapping = {'orbit': 'outputfileOrbit', 'covariance': 'outputfileCovariance', 'prediction_covariance': 'outputfileCovarianceObservationEpochs'}
    verified = {}
    for key, tag in mapping.items():
        verified[key] = pinned(exports[key], folder)
        require(verified[key] == paths[tag], 'Manifest export differs from final XML: ' + key)
    checks = compare_arrays(bounded_npz(estimate_path), orbit_table(verified['orbit']),
                            covariance_table(verified['covariance']), covariance_table(verified['prediction_covariance']))
    for pin in (entry['backend'], entry['strict'], request_pin, estimate, profile, config, native, *exports.values()):
        pinned(pin, owner)
    return {'status': 'export_consistency_passed', 'passed': True, 'backend_outcome': recorded,
            'final_folder': str(folder), 'checks': checks,
            'note': 'Native binary orbit hash/role is linked but binary payload is not decoded. This checks saved ASCII/NPZ consistency, not full independent covariance reconstruction.'}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    outcome = {'schema': 'candidate06-export-audit-v1', 'approved': False, 'release_authority': False,
               'covariance_authority': False, 'all_exports_consistent': False, 'outcomes': [], 'error': None}
    try:
        manifest_path = pinned({'path': str(args.manifest), 'sha256': args.manifest_sha256})
        manifest = small_json(manifest_path)
        require(set(manifest) == {'schema', 'stages'} and manifest['schema'] == 'candidate06-export-audit-input-v1', 'Unknown manifest contract')
        require([x['stage'] for x in manifest['stages']] == list(STAGES), 'Both planned cold outcomes must occur once in order')
        for entry in manifest['stages']:
            row = {'stage': entry['stage']}
            try:
                row.update(audit_stage(entry))
            except Unavailable as exc:
                row.update(status='unavailable', passed=False, error=str(exc))
            except Exception as exc:
                row.update(status='failed', passed=False, error=repr(exc))
            outcome['outcomes'].append(row)
        outcome['all_exports_consistent'] = all(x['passed'] for x in outcome['outcomes'])
    except Exception as exc:
        outcome['error'] = repr(exc)
        outcome['outcomes'] = [{'stage': s, 'status': 'unavailable_manifest', 'passed': False} for s in STAGES]
    write_new_json(args.output, outcome)
    return 0 if outcome['all_exports_consistent'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
