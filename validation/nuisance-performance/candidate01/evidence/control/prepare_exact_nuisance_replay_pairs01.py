#!/usr/bin/env python3
"""Prepare exact archived failure-replay cache pairs; never execute native code."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path('/home/emper/orbit-nuisance-performance')
OUT = BASE / 'replay-pairs01'
INV = BASE / 'control/exact-nuisance-replays-local-inputs01.json'
INV_SHA = '8526cff36c95ab165d7d29770387a55c356c90e5ba24116422475e1140e47984'
ORDER = [('old_nuisance_replay', 0), ('old_nuisance_replay', 1),
         ('candidate1_nuisance_replay', 1), ('candidate1_nuisance_replay', 0)]

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def record(old):
    p = Path(old['path'])
    before = p.stat()
    actual = sha(p)
    after = p.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Input changed during hashing: ' + str(p))
    if actual != old['sha256'] or before.st_size != old['bytes']:
        raise ValueError('Input differs from exact replay inventory: ' + str(p))
    return dict(bytes=before.st_size, device=before.st_dev, inode=before.st_ino,
                is_symlink=p.is_symlink(), path=str(p), resolved_path=str(p.resolve()), sha256=actual)

def structural(e):
    return (e.tag, tuple(sorted(e.attrib.items())), (e.text or '').strip(), tuple(structural(c) for c in e))

def main():
    if sha(INV) != INV_SHA: raise ValueError('Inventory changed')
    inv = json.loads(INV.read_text())
    cases = {c['role']: c for c in inv['cases']}
    if set(cases) != {r for r, _ in ORDER}: raise ValueError('Case identity')
    checked = {}
    for role, case in cases.items():
        if not case['original_pin_matches'] or not case['all_explicit_inputs_available'] or case['unique_input_file_count'] != 177:
            raise ValueError('Unverified original replay')
        checked[role] = (record(case['source_profile']), [record(f) for f in case['inputs']])
    OUT.mkdir(exist_ok=False)
    jobs = []
    for role, cache in ORDER:
        name = role + '-accumulate0-cache' + str(cache)
        root = OUT / name
        root.mkdir()
        source, inputs = checked[role]
        original = ET.parse(source['path'])
        document = ET.parse(source['path'])
        remapping = []
        for e in document.getroot().iter():
            if not (e.tag.startswith('outputfile') or e.attrib.get('label') == 'tmpDir'): continue
            before = (e.text or '').strip()
            if e.attrib.get('label') == 'tmpDir': after = root / 'tmp'
            elif e.tag == 'outputfilePrefix': after = root / 'qr'
            else: after = root / 'output' / e.tag / Path(before).name
            if after.exists() or not after.resolve().is_relative_to(root): raise ValueError('Output collision')
            for f in inputs:
                ip = Path(f['resolved_path'])
                if after.resolve().is_relative_to(ip) or ip.is_relative_to(after.resolve()): raise ValueError('Input/output overlap')
            remapping.append(dict(tag=e.tag, before=before, after=str(after)))
            e.text = str(after)
            (after if e.attrib.get('label') == 'tmpDir' else after.parent).mkdir(parents=True, exist_ok=True)
        if len(remapping) != 8: raise ValueError('Unexpected outputs')
        if list(document.getroot().iter('accumulateEpochObservations')): raise ValueError('Unexpected existing accumulation override')
        steps = list(document.getroot().iter('processingStep'))
        parents = {child: parent for parent in document.getroot().iter() for child in parent}
        if len(steps) != 2 or parents[steps[0]].tag != 'GnssProcessing': raise ValueError('Unexpected processing steps')
        step = ET.Element('processingStep')
        block = ET.SubElement(step, 'selectNormalsBlockStructure')
        ET.SubElement(block, 'accumulateEpochObservations').text = '0'
        parent = parents[steps[0]]
        parent.insert(list(parent).index(steps[0]), step)
        profile = root / 'profile.xml'
        with profile.open('xb') as f: document.write(f, encoding='utf-8', xml_declaration=True)
        # Reconstruct source semantically, including all original controls.
        rebuilt = ET.parse(profile)
        outputs = [e for e in rebuilt.getroot().iter() if e.tag.startswith('outputfile') or e.attrib.get('label') == 'tmpDir']
        for e, r in zip(outputs, remapping): e.text = r['before']
        rebuilt_parents = {child: parent for parent in rebuilt.getroot().iter() for child in parent}
        inserted = next(rebuilt.getroot().iter('selectNormalsBlockStructure'))
        inserted_step = rebuilt_parents[inserted]
        rebuilt_parents[inserted_step].remove(inserted_step)
        if structural(rebuilt.getroot()) != structural(original.getroot()): raise ValueError('Changed original XML semantics')
        jobs.append(dict(name=name, method=role, cache=cache, accumulate=0,
                         profile=str(profile), profile_sha256=sha(profile),
                         source_profile=source, output_remapping=remapping, input_files=inputs))
    plan = dict(schema='orbit-poc-nuisance-pair-preparation-v1',
                fixture_inventory=dict(path=str(INV), sha256=INV_SHA),
                purpose='Exact archived nuisance-failure replays: cache arithmetic equivalence and diagnostic timing; not a frozen benchmark replacement or release gate',
                status='prepared_not_launched', defaults_and_correctness_thresholds='unchanged',
                predeclared_order=[j['name'] for j in jobs], jobs=jobs, cpu=0,
                one_numerical_thread=True, max_process_tree_rss_bytes=8589934592, timeout_seconds=7200)
    preparation = OUT / 'preparation.json'
    with preparation.open('x') as f:
        json.dump(plan, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')
    print(json.dumps(dict(preparation=str(preparation), sha256=sha(preparation), jobs=len(jobs),
                         original_inputs_rehashed=True, native_executions=0)))

if __name__ == '__main__': main()
