"""Typed initializer tests; native GNSS equivalence is a separate gate."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'groops/extension'
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

@pytest.fixture(scope='module')
def codec(tmp_path_factory):
    out=tmp_path_factory.mktemp('warm-codec')/'fixture'
    subprocess.run(['/usr/bin/g++','-std=c++17','-O1','-I',str(EXT),str(ROOT/'tests/nuisance_warm_fixture.cpp'),'-o',str(out)],check=True)
    return out

CASES=['matrix_vector','sha','roundtrip','disabled','export','floor','nonfresh','rank','nonconverged','import','lock',
'unknown_switch','unknown_mode','disabled_option','bad_context','existing_output','existing_receipt',
'context','chart','origin','mode','unknown_record','duplicate_record','missing_record','prior','weight','basis','raw_epoch','track',
'ineligible_source','digest','missing_digest','orphan_digest','trailing','truncated','late_nan','schema','oversized_string','refresh_iono','refresh_anchor','refresh_coordinate']
@pytest.mark.parametrize('case',CASES)
def test_typed_state(codec,tmp_path,case):
    env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_')}
    subprocess.run([str(codec),case,str(tmp_path)],env=env,check=True,capture_output=True,text=True)
    if case in {'export','floor','nonfresh','rank','nonconverged'}:
        data=json.loads((tmp_path/'output.json').read_text())
        assert data['export_status']==('exported' if case=='export' else 'ineligible')
        assert data['invariants']=={'target_cold_ionosphere_unchanged':True,'target_clock_prior_anchors_unchanged':True}
        assert data['imported']=={'used':False,'path':'','sha256':''}
        assert bool(data['payload_sha256'])==(case=='export')

@pytest.fixture
def build_module():return load(ROOT/'scripts/build_groops.py','warm_build_test')
def run_build(monkeypatch,m,tmp_path,flags):
    source=tmp_path/'native';source.mkdir(exist_ok=True)
    build=tmp_path/'build';calls=[]
    monkeypatch.setattr(m,'run',lambda args,**kwargs:calls.append([str(x) for x in args]))
    monkeypatch.setattr(m.subprocess,'check_output',lambda *args,**kwargs:m.COMMIT+'\n')
    monkeypatch.setattr(sys,'argv',['build_groops.py','--source-dir',str(source),'--build-dir',str(build),'--configure-only',*flags])
    return source,calls

def test_build_requires_numerics_before_source_access(monkeypatch,build_module,tmp_path):
    m=build_module
    monkeypatch.setattr(sys,'argv',['build_groops.py','--source-dir',str(tmp_path/'absent'),'--build-dir',str(tmp_path/'build'),'--nuisance-warm-starts'])
    monkeypatch.setattr(m,'run',lambda *a,**k:pytest.fail('source/build accessed'))
    with pytest.raises(SystemExit):m.main()
    assert not (tmp_path/'absent').exists()

@pytest.mark.parametrize('flags,error',[
    (['--numerics'],'retain --nuisance-warm-starts'),
    (['--numerics','--nuisance-warm-starts','--segmented'],'profile differs'),
    (['--numerics','--nuisance-warm-starts','--nuisance-performance'],'profile differs')])
def test_build_reentry_rejects_before_mutation(monkeypatch,build_module,tmp_path,flags,error):
    m=build_module;source,calls=run_build(monkeypatch,m,tmp_path,flags)
    (source/'orbit-poc-nuisance-warm-extension.json').write_text('{}')
    with pytest.raises(ValueError,match=error):m.main()
    assert calls==[]

def test_build_reentry_verifies_only_then_configures(monkeypatch,build_module,tmp_path):
    m=build_module;source,calls=run_build(monkeypatch,m,tmp_path,['--numerics','--nuisance-warm-starts'])
    (source/'orbit-poc-nuisance-warm-extension.json').write_text('{}');m.main()
    assert len(calls)==2
    assert Path(calls[0][1]).name=='native_nuisance_warm.py'
    assert calls[1][0]=='cmake'

def test_build_new_installer_order(monkeypatch,build_module,tmp_path):
    m=build_module;source,calls=run_build(monkeypatch,m,tmp_path,['--numerics','--segmented','--wide-tangent-candidate','--nuisance-performance','--nuisance-warm-starts']);m.main()
    assert [Path(c[1]).name for c in calls[:-1]]==['apply_extension.py','native_segmented.py','native_tangent_wide.py','native_nuisance_performance.py','native_nuisance_warm.py']

@pytest.fixture
def installer():return load(EXT/'native_nuisance_warm.py','warm_installer_test')
@pytest.fixture
def stub_tree(tmp_path,installer):
    root=tmp_path/'generated';root.mkdir()
    for name in installer.paths():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        base=path.name
        if base=='gnssParametrization.h':
            body='#include "base/import.h"\n  /// Constructor.\n  virtual ~GnssParametrizationBase() {}\n'
        elif base=='gnssParametrization.cpp':
            body='void GnssParametrization::initParameter(GnssNormalEquationInfo &normalEquationInfo)\n{\n  try\n  {\n  }\n}\n'
        elif base=='gnssProcessingStepOrbitPocNumerics.h':body=(EXT/base).read_text()
        elif base=='gnssParametrizationLogDensityOu.h':body=(EXT/base).read_text()
        elif base.endswith('.h'):
            classname='G'+base[1:-2]
            body=f'  {classname}(Config &config);\n'
            if base=='gnssParametrizationCodeBiases.h':body='// ORBIT_POC_FULL_BIAS_COORDINATES_V31\n'+body
        else:body='// fixture original\n'
        path.write_text(body)
    (root/'source/gnss/gnssProcessingStep/gnssProcessingStep.cpp').write_text('// ORBIT_POC_TRANSACTIONAL_NUISANCE_V31\n')
    (root/'source/misc/orbitPoc').mkdir(parents=True)
    return root

def tree_bytes(root):return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

def test_install_is_pinned_idempotent_and_accepts_copied_headers(stub_tree,installer):
    for name in installer.HEADERS:(stub_tree/'source/misc/orbitPoc'/name).write_bytes((EXT/name).read_bytes())
    manifest=installer.apply(stub_tree);before=tree_bytes(stub_tree)
    assert installer.apply(stub_tree)==manifest
    assert tree_bytes(stub_tree)==before
    assert manifest['runtime_default']=='0'
    assert set(manifest['installed_files'])==set(installer.paths())|{'source/misc/orbitPoc/'+name for name in installer.HEADERS}
    for name,sha in manifest['installed_files'].items():assert installer.digest((stub_tree/name).read_bytes())==sha

@pytest.mark.parametrize('mutation',['last_anchor','partial_marker','header','prerequisite'])
def test_install_rejects_all_inputs_before_mutation(stub_tree,installer,mutation):
    if mutation=='last_anchor':
        p=stub_tree/installer.paths()[-1];p.write_text(p.read_text().replace('    if(!converged&&!floorLimited) throw(Exception("nuisance profiling exhausted its iteration limit"));',''))
    elif mutation=='partial_marker':
        p=stub_tree/installer.paths()[0];p.write_text('// '+installer.MARKER+'\n'+p.read_text())
    elif mutation=='header':(stub_tree/'source/misc/orbitPoc'/installer.HEADERS[0]).write_text('wrong')
    else:(stub_tree/'source/gnss/gnssProcessingStep/gnssProcessingStep.cpp').write_text('missing corrected profile')
    before=tree_bytes(stub_tree)
    with pytest.raises(ValueError):installer.apply(stub_tree)
    assert tree_bytes(stub_tree)==before

@pytest.mark.parametrize('mutation',['file','inventory','installer_input'])
def test_reentry_rejects_changed_installed_identity(stub_tree,installer,mutation):
    installer.apply(stub_tree)
    if mutation=='file':
        p=stub_tree/installer.paths()[0];p.write_bytes(p.read_bytes()+b'\n')
    else:
        p=stub_tree/installer.MANIFEST;data=json.loads(p.read_text())
        if mutation=='inventory':data['installed_files'].pop(installer.paths()[0])
        else:data['installer_inputs']['native_nuisance_warm.py']='0'*64
        p.write_text(json.dumps(data))
    before=tree_bytes(stub_tree)
    with pytest.raises(ValueError):installer.apply(stub_tree)
    assert tree_bytes(stub_tree)==before

@pytest.fixture(scope='module')
def collector(tmp_path_factory):
    root=tmp_path_factory.mktemp('warm-collector');out=root/'fixture'
    # Only declarations are replaced. The full production collector body runs.
    for name in ['gnss/gnssParametrization/gnssParametrization.h','gnss/gnssReceiver.h','gnss/gnssTransmitter.h']:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('// declarations supplied by fixture\n')
    misc=root/'misc/orbitPoc';misc.mkdir(parents=True)
    (misc/'nuisanceWarmState.h').write_bytes((EXT/'nuisanceWarmState.h').read_bytes())
    subprocess.run(['/usr/bin/g++','-std=c++17','-O1','-I',str(root),'-I',str(EXT),str(ROOT/'tests/nuisance_warm_gnss_fixture.cpp'),'-o',str(out)],check=True)
    return out

@pytest.mark.parametrize('case',['track_swap','track_null','duplicate_track','nonmember_track','wrong_receiver','raw_time','clock_value','observation_value','weight','bias_shape'])
def test_production_collector(collector,case):
    subprocess.run([str(collector),case],check=True,capture_output=True,text=True)
