"""Injected runner tests: no native process, real inputs, or benchmark writes."""
from pathlib import Path
from types import SimpleNamespace
import copy
import importlib.util
import json
import os
import xml.etree.ElementTree as ET
import pytest

ROOT=Path(__file__).resolve().parents[1]
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True))
def load_runner():
    spec=importlib.util.spec_from_file_location('warm_profile_runner_test',ROOT/'scripts/run_nuisance_warm_profiles.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def xml_template(path,shared,physical):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(f'''<groops><filename label="tmpDir">{path.parent}/tmp</filename><program><GnssProcessing>
<parametrization><leoDynamicOrbits><inputfileVariational>{physical}</inputfileVariational><outputfileOrbit>{path.parent}/output/orbit.txt</outputfileOrbit></leoDynamicOrbits></parametrization>
<inputfileObservation>{shared}</inputfileObservation><processingStep><orbitPocNumerics><outputfilePrefix>{path.parent}/qr</outputfilePrefix></orbitPocNumerics></processingStep><processingStep><writeResults/></processingStep>
</GnssProcessing></program></groops>''')

@pytest.fixture
def experiment(tmp_path,monkeypatch):
    m=load_runner();repo=tmp_path/'repo';repo.mkdir()
    # Test-only durability stub: every file is temporary, and no native process runs.
    monkeypatch.setattr(m.os,'fsync',lambda fd:None)
    files={}
    for name in ['src/orbit_poc/segmented/supervisor.py','src/module.py','groops/extension/example.h','scripts/run_nuisance_warm_profiles.py','scripts/check_nuisance_warm_profiles.py','python','native-bin','lib.so','native-source/example.cpp']:
        p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name+'\n');files[name]=p
    monkeypatch.setattr(m,'REPO',repo);monkeypatch.setattr(m,'__file__',str(files['scripts/run_nuisance_warm_profiles.py']))
    monkeypatch.setattr(m,'sys',SimpleNamespace(executable=str(files['python'])))
    admissions=[]
    def admit():admissions.append(True);return {'host':'fixture','boot_id':'fixture-boot','cpu':0,'threads':1,'native_processes':[]}
    monkeypatch.setattr(m,'admission',admit)
    manifest=repo/'manifest.json';dump(manifest,{'nuisance_warm_extension':{'runtime_default':'0'}})
    build=repo/'build.json';dump(build,{'execution':{'status':'complete'},'inputs_and_originals_unchanged':True,'native':m.pin(files['native-bin']),
        'build_manifest':m.pin(manifest),'libraries':[m.pin(files['lib.so'])],
        'runtime_environment':{'LD_LIBRARY_PATH':str(repo)},
        'source_root':str(repo/'native-source'),'patched_source':{'example.cpp':m.digest(files['native-source/example.cpp'])}})
    prepared=tmp_path/'prepared';shared=prepared/'shared.dat';shared.parent.mkdir();shared.write_text('fixed observations\n')
    copies=[];points=[]
    for name in ['source','source_repeat','target','target_repeat']:
        physical=prepared/name/'physical.dat';physical.parent.mkdir();physical.write_text('target\n' if name.startswith('target') else 'source\n')
        original=prepared/name/'original.dat';original.write_bytes(physical.read_bytes())
        record={**m.pin(original),'copy':str(physical),'copy_sha256':m.digest(physical)};copies.append(record)
        template=prepared/name/'template.xml';xml_template(template,shared,physical)
        points.append({'name':name,'profile_template':m.pin(template),'input_paths':[str(shared),str(physical)],'physical':{'initial':m.pin(original)}})
    prep=prepared/'preparation.json';dump(prep,{'copies':copies,'groups':[{'name':'pulses','method':'pulses','points':points}]})
    out=tmp_path/'experiment'
    def prepare():m.prepare(SimpleNamespace(output=out,preparation=prep,build_record=build));return m.read(out/'freeze.json')
    calls=[];behavior={}
    def execute(cmd,**kw):
        d=Path(kw['cwd']);env=kw['env'];name=d.name;calls.append({'command':cmd,'env':dict(env),'kwargs':kw})
        status=behavior.get('status',{}).get(name,'complete');clean=behavior.get('clean',{}).get(name,True)
        result={'status':status,'returncode':0 if status=='complete' else 1,'elapsed_seconds':.25,'owned_process_group_cleaned':clean}
        m.save(kw['receipt_path'],result);Path(kw['log_path']).write_text('fixture only\n')
        if status=='complete':
            prefix=d/'qr';generation=d/'qr.11'
            dump(Path(str(prefix)+'.profile.json'),{'nuisance_converged':True,'nuisance_floor_limited':False,'iterations':10,'threshold_m':1e-8,'required_consecutive_small_updates':2,'maximum_update_m':1e-9,'history':[{'maximum_update_m':1e-9}]*10})
            dump(Path(str(generation)+'.diagnostics.json'),{'rank_status':'full','lambda':0,'rank':1,'retained_parameters':1})
            if env['ORBIT_POC_NUISANCE_WARM_STARTS']=='1':
                payload=Path(env['ORBIT_POC_NUISANCE_WARM_OUTPUT']);payload.write_bytes(b'fixture seed bytes')
                companion={'schema':'orbit-poc-native-nuisance-warm-state-v1','mode':env['ORBIT_POC_NUISANCE_WARM_MODE'],
                    'context_sha256':env['ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256'],'chart_sha256':'a'*64,'cold_origin_sha256':'b'*64,
                    'source_prefix':str(prefix),'source_generation':str(generation),'counts':{'coordinates':5},
                    'eligibility':{'fresh_undamped':True,'nuisance_converged':True,'nuisance_floor_limited':False,'rank_status':'full'},
                    'invariants':{'target_cold_ionosphere_unchanged':True,'target_clock_prior_anchors_unchanged':True},
                    'export_status':'exported','payload_sha256':m.digest(payload),
                    'imported':{'used':'ORBIT_POC_NUISANCE_WARM_INPUT' in env,'path':env.get('ORBIT_POC_NUISANCE_WARM_INPUT',''),'sha256':env.get('ORBIT_POC_NUISANCE_WARM_INPUT_SHA256','')}}
                update=behavior.get('companion',{}).get(name)
                if update:update(companion)
                dump(Path(str(payload)+'.json'),companion)
        mutate=behavior.get('after',{}).get(name)
        if mutate:mutate(d,env)
        return result
    monkeypatch.setattr(m,'run_owned',execute)
    return SimpleNamespace(m=m,repo=repo,prep=prep,build=build,out=out,prepare=prepare,calls=calls,behavior=behavior,admissions=admissions,shared=shared)

def run(e):e.m.run(SimpleNamespace(freeze=e.out/'freeze.json'))
def execution(e,name):return e.m.read(e.out/('pulses--'+name)/'execution.json')

def test_prepare_preserves_inputs_config_syntax_and_dependency_order(experiment):
    e=experiment;before={p:p.read_bytes() for p in e.prep.parent.rglob('*') if p.is_file()};f=e.prepare()
    assert len(f['jobs'])==9 and f['execution_order']==[j['id'] for j in f['jobs']]
    assert f['limits']=={'timeout_seconds':900,'max_process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':16*1024**3,'cpu':0,'threads':1}
    for j in f['jobs']:
        root=ET.parse(Path(j['root'])/'config.xml').getroot();steps=root.findall('.//GnssProcessing/processingStep')
        assert [next(iter(s)).tag for s in steps]==['orbitPocNumerics','writeResults','writeResiduals']
        residual=steps[-1].find('writeResiduals');assert residual.find('selectReceivers/all') is not None
        assert residual.findtext('outputfileResiduals')==str(Path(j['root'])/'diagnostic/residuals.{station}.xml')
        assert root.findtext('.//inputfileObservation')==str(e.shared)
        for node in root.iter():
            if node.tag.startswith('outputfile') or node.attrib.get('label')=='tmpDir':assert Path(node.text).resolve().is_relative_to(Path(j['root']))
        assert j['environment']['ORBIT_POC_NUISANCE_WARM_STARTS']==('0' if j['treatment']=='disabled' else '1')
    assert all(p.read_bytes()==b for p,b in before.items())
    with pytest.raises(FileExistsError):e.prepare()

def test_normal_run_scrubs_environment_keeps_full_limits_and_preserves_inputs(experiment,monkeypatch):
    e=experiment;f=e.prepare();monkeypatch.setenv('ORBIT_POC_NUISANCE_WARM_INPUT','/unowned/seed');monkeypatch.setenv('ORBIT_POC_UNKNOWN_CONTROL','1');monkeypatch.setenv('PYTHONPATH','/unowned');monkeypatch.setenv('PYTHONHOME','/unowned');before=e.shared.read_bytes()
    run(e);assert len(e.calls)==9
    for call,job_id in zip(e.calls,f['execution_order']):
        j=next(x for x in f['jobs'] if x['id']==job_id);env=call['env']
        assert 'ORBIT_POC_UNKNOWN_CONTROL' not in env and 'PYTHONPATH' not in env and 'PYTHONHOME' not in env
        assert env['OPENBLAS_NUM_THREADS']==env['OMP_NUM_THREADS']==env['MKL_NUM_THREADS']=='1'
        assert call['command']==['/usr/bin/taskset','-c','0',f['native']['path'],str(Path(j['root'])/'config.xml')]
        assert call['kwargs']['timeout_seconds']==900 and call['kwargs']['max_process_tree_rss_bytes']==8*1024**3
        assert ('ORBIT_POC_NUISANCE_WARM_INPUT_SHA256' in env)==(j['treatment']=='warm')
        rec=e.m.read(Path(j['root'])/'execution.json');assert rec['inputs_unchanged'] and rec['status']=='complete'
    assert e.shared.read_bytes()==before
    with pytest.raises(FileExistsError):run(e)

@pytest.mark.parametrize('kind',['extra_file','symlink','admission','supervisor','execution'])
def test_started_or_unexpected_attempt_never_runs(experiment,kind):
    e=experiment;f=e.prepare();d=Path(f['jobs'][0]['root'])
    if kind=='symlink':(d/'outside').symlink_to(e.shared)
    else:(d/({'extra_file':'qr.stale'}.get(kind,kind+'.json'))).write_text('preserved')
    before={p:p.read_bytes() for p in d.rglob('*') if p.is_file()}
    with pytest.raises((ValueError,FileExistsError)):run(e)
    assert e.calls==[] and all(p.read_bytes()==b for p,b in before.items())

@pytest.mark.parametrize('kind',['input','config','native','library','patched_source'])
def test_changed_frozen_file_prevents_launch(experiment,kind):
    e=experiment;f=e.prepare();mapping={'input':e.shared,'config':Path(f['jobs'][0]['root'])/'config.xml','native':Path(f['native']['path']),'library':e.repo/'lib.so','patched_source':e.repo/'native-source/example.cpp'}
    p=mapping[kind];p.write_bytes(p.read_bytes()+b'changed')
    with pytest.raises(ValueError):run(e)
    assert e.calls==[]

def test_timeout_is_preserved_and_only_its_dependents_block(experiment):
    e=experiment;e.prepare();e.behavior['status']={'pulses--cold_source_full':'timeout'};run(e)
    assert execution(e,'cold_source_full')['status']=='timeout'
    assert execution(e,'warm_source_full')['status']==execution(e,'warm_target_full')['status']=='blocked'
    assert execution(e,'warm_target_clock')['status']=='complete'
    assert len(e.calls)==7

def test_unclean_cleanup_stops_after_preserving_attempt(experiment):
    e=experiment;e.prepare();e.behavior['clean']={'pulses--disabled_source':False};run(e)
    assert len(e.calls)==1 and execution(e,'disabled_source')['owned_process_group_cleaned'] is False
    report=e.m.read(e.out/'run-result.json');assert report['planned']==9 and report['completed']==1

@pytest.mark.parametrize('mutation',['input','freeze','donor'])
def test_postrun_identity_change_is_recorded_and_stops(experiment,mutation):
    e=experiment;e.prepare();name='pulses--warm_source_full' if mutation=='donor' else 'pulses--disabled_source'
    def alter(d,env):
        p=e.shared if mutation=='input' else e.out/'freeze.json' if mutation=='freeze' else Path(env['ORBIT_POC_NUISANCE_WARM_INPUT'])
        if mutation=='freeze':
            value=e.m.read(p);value['limits']['timeout_seconds']=999;dump(p,value)
        else:p.write_bytes(p.read_bytes()+b'changed')
    e.behavior['after']={name:alter};run(e)
    rec=e.m.read(e.out/name/'execution.json');assert rec['status']=='identity_failure' and rec['inputs_unchanged'] is False
    assert len(e.calls)==(4 if mutation=='donor' else 1)

@pytest.mark.parametrize('field',['mode','context_sha256','source_prefix','source_generation','schema','counts','counts_bool','counts_float','counts_large','invariants','invariants_numeric','numeric_eligibility','chart_sha256','cold_origin_sha256','imported'])
def test_ineligible_or_misattributed_donor_blocks_before_native(experiment,field):
    e=experiment;e.prepare()
    def alter(value):
        if field=='counts':value[field]={'coordinates':0}
        elif field=='counts_bool':value['counts']['coordinates']=True
        elif field=='counts_float':value['counts']['coordinates']=5.0
        elif field=='counts_large':value['counts']['coordinates']=1000001
        elif field=='invariants':value[field]['target_cold_ionosphere_unchanged']=False
        elif field=='invariants_numeric':value['invariants']['target_clock_prior_anchors_unchanged']=1
        elif field=='imported':value[field]={'used':True,'path':'/other','sha256':'a'*64}
        elif field=='numeric_eligibility':value['eligibility']['nuisance_converged']=1
        else:value[field]='wrong'
    e.behavior['companion']={'pulses--cold_source_full':alter};run(e)
    assert execution(e,'warm_source_full')['status']=='blocked'
    assert execution(e,'warm_target_full')['status']=='blocked'
    assert not any(c['kwargs']['cwd'].name in {'pulses--warm_source_full','pulses--warm_target_full'} for c in e.calls)

def test_runtime_cannot_override_one_numerical_thread(experiment):
    e=experiment;build=e.m.read(e.build);build['runtime_environment']['OPENBLAS_NUM_THREADS']='4';dump(e.build,build)
    try:f=e.prepare()
    except ValueError:return
    assert all(j['environment']['OPENBLAS_NUM_THREADS']=='1' for j in f['jobs'])

def test_configure_rejects_parent_path_output_escape(experiment,tmp_path):
    e=experiment;template=tmp_path/'source/template.xml';xml_template(template,e.shared,e.shared)
    tree=ET.parse(template);tree.find('.//outputfileOrbit').text=str(template.parent/'../outside-orbit');tree.write(template)
    d=tmp_path/'isolated/config.xml';d.parent.mkdir()
    with pytest.raises(ValueError):e.m.configure(template,d)
    assert not (tmp_path/'outside-orbit').exists()
