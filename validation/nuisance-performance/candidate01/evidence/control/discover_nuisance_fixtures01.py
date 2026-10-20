#!/usr/bin/env python3
"""Read and pin two preserved real GNSS profiles; never run or modify them."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import xml.etree.ElementTree as ET

CONTROL = Path('/home/emper/orbit-nuisance-performance/control')
BASE = Path('/mnt/d/orbit-numerics-v3.1/correctness/validation-02')
OUTPUT = CONTROL / 'fixture-discovery01.json'
CACHE = {}


def pin(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'Missing regular input: {path}')
    resolved = path.resolve(strict=True)
    before = resolved.stat()
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if identity not in CACHE:
        digest = hashlib.sha256()
        with resolved.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        after = resolved.stat()
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError(f'Input changed while hashing: {path}')
        CACHE[identity] = digest.hexdigest()
    return {'path': str(path), 'resolved_path': str(resolved), 'bytes': before.st_size,
            'sha256': CACHE[identity], 'is_symlink': path.is_symlink(),
            'device': before.st_dev, 'inode': before.st_ino}


def discover(method):
    profile = BASE / f'objective-{method}/point-001-nonzero-full-prior/profile.xml'
    profile_pin = pin(profile)
    root = ET.parse(profile).getroot()
    transmitter_list = root.find('.//inputfileTransmitterList').text.strip()
    prns = Path(transmitter_list).read_text().split()
    if prns != [f'G{i:02d}' for i in range(1, 33)]:
        raise ValueError('Unexpected preserved GPS transmitter list')
    references, paths, outputs = [], set(), []
    for element in root.iter():
        value = (element.text or '').strip()
        if not value or list(element):
            continue
        is_input = (element.tag.startswith('inputfile') or
                    element.tag == 'filename' and
                    element.attrib.get('label') == 'orbitPocCanonicalAttitude')
        if is_input:
            expanded = [value.replace('{prn}', prn) for prn in prns] if '{prn}' in value else [value]
            if any('{' in path or '}' in path or not Path(path).is_absolute() for path in expanded):
                raise ValueError(f'Unresolved input expression: {value}')
            paths.update(expanded)
            references.append({'tag': element.tag, 'attributes': element.attrib,
                               'literal': value, 'expanded_paths': expanded})
        if element.tag.startswith('outputfile') or element.attrib.get('label') == 'tmpDir':
            outputs.append({'tag': element.tag, 'attributes': element.attrib, 'literal': value})
    files = [pin(path) for path in sorted(paths)]
    if len(files) != 177:
        raise ValueError(f'Preserved input inventory changed: {len(files)}')
    nested_xml = []
    for entry in files:
        path = Path(entry['path'])
        if path.suffix != '.xml':
            continue
        tree = ET.parse(path).getroot()
        extra = [element.text.strip() for element in tree.iter()
                 if element.tag.startswith('inputfile') and (element.text or '').strip()]
        if extra:
            raise ValueError(f'Uninventoried nested XML inputs in {path}: {extra}')
        nested_xml.append(entry['path'])
    execution = profile.parent / 'profile.execution.json'
    prior = json.loads(execution.read_text())
    diagnostics = profile.parent / 'qr.1.diagnostics.json'
    counts = json.loads(diagnostics.read_text())
    return {'method': method, 'profile': profile_pin,
            'duration_seconds': 3600, 'input_count': len(files),
            'input_bytes_counting_distinct_paths': sum(file['bytes'] for file in files),
            'files': files, 'input_references': references,
            'nested_xml_checked_for_additional_inputfile_references': nested_xml,
            'output_and_temporary_locations_must_be_remapped': outputs,
            'historical_execution': {'artifact': pin(execution),
                'native_binary_sha256': prior['native_binary_sha256'],
                'elapsed_seconds': prior['elapsed_seconds'], 'returncode': prior['returncode']},
            'historical_first_qr': {'artifact': pin(diagnostics), **{
                key: counts[key] for key in ('local_parameters', 'retained_parameters',
                                            'source_rows', 'reduced_rows')}}}


def main():
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    cases = [discover(method) for method in ('pulses', 'log_drag_ou')]
    value = {'schema': 'orbit-poc-nuisance-preserved-fixture-discovery-v1',
             'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'tool': pin(Path(__file__)),
             'scope': 'Read-only discovery and hashing of explicitly referenced local profile inputs; no native run or fixture mutation.',
             'limitations': [
                 'These are preserved older validation-02 inputs, originally evaluated using fcfbc385917227084d11e3330c1e6da4d0d6df82f0e683ead2276ce70e16d2b8, not the final corrected numerical reference.',
                 'Use the same newly built executable with optimization off/on for equivalence. Historical timings are not measurements of that executable or speedup evidence.',
                 'Input reachability was checked through profile inputfile fields, its explicit canonical-attitude variable, GPS PRN expansion, and nested XML inputfile fields. This is not a full runtime/library inventory.',
                 'Every outputfile field, temporary directory, environment-controlled QR prefix and row spool must target a fresh isolated output before execution.'
             ], 'cases': cases}
    with OUTPUT.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'manifest': pin(OUTPUT), 'case_input_counts': [case['input_count'] for case in cases]}))


if __name__ == '__main__':
    main()
