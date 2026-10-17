from pathlib import Path
import datetime, hashlib, json, xml.etree.ElementTree as ET

B = Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
R = B / 'preparation-02/backings/run'
CAN = B / 'validation-03/run'
SRC = B / 'validation-03/source'
BAD = '9f71eb67221fe67a092ea4566e05bce837b47c5c4e6a2d917909ced474aa03c4'

def pin(p):
    p = Path(p)
    raw = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

def resolve(p):
    p = Path(p)
    try:
        return R / p.relative_to(CAN)
    except ValueError:
        return p

root = R / 'preparation/prefixes' / BAD / 'nominal-initialization'
init = json.loads((root / 'initialization.json').read_bytes())
expected = '0019b9df924b30f7c1ded518533db1e1a9dc2f1fc8571d6fbe9797bab0fd6655'
assert init['helper_sha256'] == expected
assert pin(SRC / 'src/orbit_poc/comparison/initialization.py')['sha256'] == expected
configs = []
for execution in init['executions']:
    xml = resolve(execution['command'][1])
    identity = pin(xml)
    assert identity['sha256'] == execution['config_sha256']
    programs = ET.parse(xml).getroot().findall('.//PreprocessingVariationalEquation')
    assert len(programs) == 1
    profile = programs[0].find('orbitPocDerivativeProfile')
    assert profile is None
    configs.append({'configuration': identity, 'explicit_derivative_profile': None,
                    'native_default': 'legacy_v3'})

names = ['groops/extension/native_derivatives.py',
         'groops/extension/native_synthetic_force.py',
         'groops/extension/stagedVariationalBody.h',
         'groops/extension/orbitPocEvaluateVariational.cpp',
         'src/orbit_poc/comparison/initialization.py',
         'src/orbit_poc/segmented/multiday.py']
files = {name: pin(SRC / name) for name in names}
derivative = (SRC / names[0]).read_text()
synthetic = (SRC / names[1]).read_text()
staged = (SRC / names[2]).read_text()
assert 'readConfig(config,"orbitPocDerivativeProfile",orbitPocDerivativeProfile,Config::DEFAULT,"legacy_v3"' in derivative
assert 'if(orbitPocDerivativeProfile=="synthetic_complete_v1")' in synthetic
assert 'preciseEquinoctialReference(' in synthetic and 'preciseSyntheticReferenceResidual(' in synthetic
assert 'if(orbitPocDerivativeProfile!="legacy_v3")' in staged
assert 'preciseReferenceMeanResidual' in staged and 'solveSixStateTangent' in staged
print(json.dumps({'schema': 'orbit-poc-preparation-numerical-path-independent-review-v1',
                  'passed': True, 'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'initialization': pin(root / 'initialization.json'),
                  'source_files': files, 'all_native_preprocessing_configurations': configs,
                  'finding': 'All eleven saved 48-hour preparation propagation configurations omit the profile field and therefore take legacy_v3. The corrected synthetic precise-reference, stable force-residual and coupled mean-solve paths are guarded by the opt-in staged profile and were not selected.',
                  'limitation': 'Source-path attribution and saved outputs establish an omitted corrected numerical path, not that selecting it will satisfy the unchanged closure thresholds. No new native evaluation was performed.'}, sort_keys=True))
