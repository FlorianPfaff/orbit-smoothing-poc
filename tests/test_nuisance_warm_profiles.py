"""Offline counterexamples for the frozen native-profile acceptance checker."""
from pathlib import Path
import copy
import importlib.util
import json
import struct
import xml.etree.ElementTree as ET
import numpy as np
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/check_nuisance_warm_profiles.py'
spec=importlib.util.spec_from_file_location('warm_profiles',SCRIPT)
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)


def save(p,v):p.write_text(json.dumps(v,sort_keys=True))
def pin(p):return {'path':str(p),'sha256':check.digest(p),'bytes':p.stat().st_size}
def matrix(p,v):
    a=np.asarray(v,dtype='<f8');p.write_bytes(struct.pack('<QQ',*a.shape)+a.tobytes())
def table(p,header,rows):p.write_text('\t'.join(header)+'\n'+''.join('\t'.join(map(str,r))+'\n' for r in rows))
def change(p,fn):
    value=check.strict_json(p);fn(value);save(p,value)


class Fixture:
    def __init__(self,root):
        self.root=root;root.mkdir(exist_ok=True);self.runs={};self.jobs=[];self.copies=[];self.points=[]
        self.native=root/'native';self.native.write_bytes(b'native frozen candidate')
        self.runner=root/'runner.py';self.runner.write_bytes(b'runner')
        self.supervisor=root/'supervisor.py';self.supervisor.write_bytes(b'supervisor')
        self.python=root/'python';self.python.write_bytes(b'python')
        self.observation=root/'observations';self.observation.write_bytes(b'identical observations and weights')
        self.copy(self.observation)
        for point in ('source','source_repeat','target','target_repeat'):
            d=root/('prepared-'+point);d.mkdir();physical={}
            for name in ('physical_initial.txt','fixed_force.txt'):
                p=d/name;p.write_text(name+('source' if point.startswith('source') else 'target'));physical[name]=pin(p);self.copy(p)
            variational=d/'variational';variational.write_text('independent closure '+point);self.copy(variational)
            reference=d/'reference';reference.write_text('independent reference '+point);self.copy(reference)
            xml=ET.Element('groops');g=ET.SubElement(ET.SubElement(xml,'program'),'GnssProcessing')
            for tag,path in [('inputfileObservations',self.observation),('inputfileVariational',variational),('inputfileNumericsReferenceParameters',reference)]:ET.SubElement(g,tag).text=str(path)
            for tag in ('codeBiases','tecBiases'):
                ET.SubElement(ET.SubElement(ET.SubElement(g,'parametrization'),tag),'sigmaZeroMeanConstraint').text='1'
            ET.SubElement(ET.SubElement(ET.SubElement(g,'processingStep'),'orbitPocNumerics'),'outputfilePrefix').text=str(d/'qr')
            template=d/'template.xml';ET.ElementTree(xml).write(template)
            self.points.append({'name':point,'physical':physical,'input_paths':[str(self.observation),str(variational),str(reference)],'profile_template':pin(template)})
        self.preparation=root/'preparation.json';save(self.preparation,{'schema':'orbit-poc-nuisance-warm-profile-preparation-v1','copies':self.copies,
                    'groups':[{'name':'pulses-bias-priors','method':'pulses','nuisance_prior_variant':True,'points':self.points}]})
        self.build=root/'build.json';save(self.build,{'native':pin(self.native),'execution':{'status':'complete'},'inputs_and_originals_unchanged':True,'patched_source':{},'source_root':str(root)})
        for name,point,treatment,mode,donor in [
            ('source','source','cold_export','receiver_clock_signal_float_v1',None),
            ('source_repeat','source_repeat','cold_export','receiver_clock_signal_float_v1',None),
            ('source_warm','source','warm','receiver_clock_signal_float_v1','source'),
            ('cold','target','cold_export','receiver_clock_signal_float_v1',None),
            ('repeat','target_repeat','cold_export','receiver_clock_signal_float_v1',None),
            ('warm','target','warm','receiver_clock_signal_float_v1','source'),
            ('disabled','target','disabled','receiver_clock_signal_float_v1',None),
            ('clock_source','source','cold_export','receiver_clock_v1',None),
            ('clock_warm','target','warm','receiver_clock_v1','clock_source')]:
            self.add_run(name,point,treatment,mode,donor)
        self.freeze=root/'freeze.json';save(self.freeze,{'schema':'orbit-poc-nuisance-warm-profile-freeze-v1','preparation':pin(self.preparation),
            'native':pin(self.native),'runner':pin(self.runner),'supervisor':pin(self.supervisor),'build_record':pin(self.build),
            'checker':pin(SCRIPT),'python':pin(self.python),'source_files':[],'jobs':self.jobs,
            'limits':{'cpu':0,'threads':1,'timeout_seconds':900,'max_process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':16*1024**3},
            'thresholds':{'strict_nuisance_update_m':1e-8,'required_consecutive_small_updates':2,'code_prediction_m':.003,'phase_prediction_m':.00003,'diagnostic_covariance_relative':1e-8}})
        self.seal()

    def copy(self,path):self.copies.append({**pin(path),'copy':str(path),'copy_sha256':check.digest(path)})

    def add_run(self,name,point,treatment,mode,donor):
        root=self.root/name;root.mkdir();self.runs[name]=root
        prepared=next(p for p in self.points if p['name']==point)
        xml=ET.parse(prepared['profile_template']['path']).getroot();xml.find('.//outputfilePrefix').text=str(root/'qr')
        res=ET.SubElement(ET.SubElement(xml.find('.//GnssProcessing'),'processingStep'),'writeResiduals')
        ET.SubElement(ET.SubElement(res,'selectReceivers'),'all');ET.SubElement(res,'outputfileResiduals').text=str(root/'diagnostic/residuals.{station}.xml')
        ET.ElementTree(xml).write(root/'config.xml')
        env={'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS':'1','ORBIT_POC_NUISANCE_WARM_STARTS':'0' if treatment=='disabled' else '1'}
        if treatment!='disabled':env.update(ORBIT_POC_NUISANCE_WARM_MODE=mode,ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256='a'*64,ORBIT_POC_NUISANCE_WARM_OUTPUT=str(root/'seed.bin'))
        if donor:env['ORBIT_POC_NUISANCE_WARM_INPUT']=str(self.runs[donor]/'seed.bin')
        inputs=[pin(Path(p)) for p in sorted(set(prepared['input_paths'])|{p['path'] for p in prepared['physical'].values()})]
        self.jobs.append({'id':name,'root':str(root),'profile_sha256':check.digest(root/'config.xml'),'group':'pulses-bias-priors','point':point,'treatment':treatment,
                          'mode':mode,'context_sha256':'a'*64,'source_donor_job_id':donor,'environment':env,'input_inventory':inputs})
        profile={'nuisance_converged':True,'nuisance_floor_limited':False,'threshold_m':1e-8,'required_consecutive_small_updates':2,
                 'fixed_weights':True,'dynamic_updates':False,'iterations':2,'maximum_update_m':1e-10,'history':[{'maximum_update_m':1e-10}]*2}
        save(root/'qr.profile.json',profile)
        for generation in range(1,4):
            stem=str(root/f'qr.{generation}');table(Path(stem+'.parameters.tsv'),['index','name','dynamic','unit','scale','coordinate_convention'],
                    [[0,'clock',0,'m',1,'native'],[1,'dynamic',1,'m',.5,'native'],[2,'bias',0,'m',2,'native']])
            table(Path(stem+'.rows.tsv'),['row','epoch','source','rhs','columns'],[[0,0,'weighted_observation',1,'0,1,2'],[1,0,'weighted_observation',2,'0,1,2'],[2,'global','code_bias_full_constraint',1,'2'],[3,'global','tec_bias_full_constraint',2,'2']])
            for suffix in ('bias_coordinates.tsv','nuisance_coordinates.tsv'):table(Path(stem+'.'+suffix),['index','name','full_native_coordinate'],[[2,'bias',1]])
            table(Path(stem+'.delta.tsv'),['index','undamped','step'],[[1,0,0],[2,0,0]])
            Path(stem+'.singular_values.txt').write_text('3\n2\n')
            save(Path(stem+'.factor.json'),{'rows':2,'columns':2,'scales':[.5,2.],'dynamic':[True,False],'retained_global_indices':[1,2],
                    'original_objective_rows':4,'objective_residual_basis':'original_weighted_rows_v1'})
            save(Path(stem+'.diagnostics.json'),{'rank_status':'full','lambda':0,'rank':2,'retained_parameters':2,'source_rows':4,'reduced_rows':3,
                    'rank_threshold':np.finfo(float).eps*9,'sigma_min':2.,'sigma_max':3.})
            save(Path(stem+'.profile.json'),{'direct_cost':5.,'rhs2':10.})
            matrix(Path(stem+'.R.bin'),[[2.,0.],[0.,3.]]);matrix(Path(stem+'.rhs.bin'),[[1.],[1.]])
            if generation<3:save(Path(stem+'.nuisance_line_search.json'),{'trials':[{'child_user_seconds':1.,'child_system_seconds':2.,'peak_child_rss_bytes':123,'actual_reduction':1.}]})
        self.residual(root)
        command=['/usr/bin/taskset','-c','0',str(self.native),str(root/'config.xml')]
        save(root/'supervisor.plan.json',{'schema':'orbit-poc-segmented-supervision-plan-v1','argv':command,'cwd':str(root),'working_directory':str(root),'receipt_path':str(root/'supervisor.json'),'log_path':str(root/'profile.log'),'timeout_seconds':900,'max_process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':16*1024**3,'helper_sha256':check.digest(self.supervisor),'boot_id':'boot'})
        save(root/'supervisor.json',{'schema':'orbit-poc-segmented-supervision-v1','status':'complete','returncode':0,'owned_process_group_cleaned':True,'cleanup':{'verified':True,'remaining':[],'empty_tree_certificate':'kernel_ECHILD'},'argv':command,'plan_sha256':check.digest(root/'supervisor.plan.json'),'helper_sha256':check.digest(self.supervisor),'boot_id':'boot'})
        if treatment!='disabled':
            (root/'seed.bin').write_bytes(('native payload '+name).encode())
            source=self.runs[donor] if donor else None
            companion={'schema':'orbit-poc-native-nuisance-warm-state-v1','mode':mode,'context_sha256':'a'*64,
                'chart_sha256':('b' if mode.endswith('float_v1') else 'c')*64,'cold_origin_sha256':('d' if mode.endswith('float_v1') else 'e')*64,
                'source_prefix':str(root/'qr'),'source_generation':str(root/'qr.3'),'payload_sha256':check.digest(root/'seed.bin'),
                'eligibility':{'nuisance_converged':True,'nuisance_floor_limited':False,'fresh_undamped':True,'rank_status':'full'},
                'imported':{'used':donor is not None,'path':str(source/'seed.bin') if donor else '','sha256':check.digest(source/'seed.bin') if donor else ''},
                'counts':{'coordinates':3 if mode.endswith('float_v1') else 1},'invariants':{'target_cold_ionosphere_unchanged':True,'target_clock_prior_anchors_unchanged':True},'export_status':'exported'}
            save(root/'seed.bin.json',companion)

    def residual(self,root,code=0.,phase=0.,sigma=.003):
        d=root/'diagnostic';d.mkdir(exist_ok=True);xml=ET.Element('groops');e=ET.SubElement(xml,'epoch')
        for name,values in [('type',['A','E','A','E','I']+['C1CG']*3+['L1CG']*3),('satellite',['G01']),('observation',[0]*5+[code,1,.3]+[phase,1,sigma])]:
            n=ET.SubElement(e,name);ET.SubElement(n,'count').text=str(len(values))
            for value in values:ET.SubElement(n,'cell').text=str(value)
        ET.ElementTree(xml).write(d/'residuals.gracefo1.xml')

    def seal(self):
        frozen=check.strict_json(self.freeze);frozen['jobs']=self.jobs;save(self.freeze,frozen)
        for job in self.jobs:
            root=Path(job['root']);donor=None;env=dict(job['environment'])
            if job['source_donor_job_id']:
                d=self.runs[job['source_donor_job_id']];donor={'root':str(d),'payload':pin(d/'seed.bin'),'companion':pin(d/'seed.bin.json')}
                env['ORBIT_POC_NUISANCE_WARM_INPUT_SHA256']=donor['payload']['sha256']
            ex={'schema':'orbit-poc-nuisance-warm-profile-execution-v1','status':'complete','returncode':0,'timed_out':False,'owned_process_group_cleaned':True,
                'command':['/usr/bin/taskset','-c','0',str(self.native),str(root/'config.xml')],'config_sha256':job['profile_sha256'],'native_binary_sha256':check.digest(self.native),
                'supervisor_sha256':check.digest(root/'supervisor.json'),'freeze':pin(self.freeze),'preparation':pin(self.preparation),'job_id':job['id'],
                **{k:job[k] for k in ('group','point','treatment','mode','context_sha256','input_inventory')},'effective_environment':env,'source_donor':donor,'elapsed_seconds':1.,'inputs_unchanged':True,'identity_error':None,'blocked_reason':None}
            ex['output_inventory']=[{**pin(p),'path':str(p.relative_to(root))} for p in sorted(root.rglob('*')) if p.is_file() and p.name!='execution.json']
            save(root/'execution.json',ex)

    def inspected(self,name):return check.inspect(self.runs[name])
    def comparison(self):return check.compare(self.inspected('cold'),self.inspected('warm'),self.inspected('repeat'))


@pytest.fixture
def experiment(tmp_path):return Fixture(tmp_path)


def test_valid_full_and_clock_modes_and_source_repeat(experiment):
    f=experiment
    assert f.comparison()['passed']
    assert check.compare(f.inspected('cold'),f.inspected('clock_warm'),f.inspected('repeat'))['passed']
    assert check.compare(f.inspected('source'),f.inspected('source_warm'),f.inspected('source_repeat'))['passed']
    assert check.inert(f.inspected('disabled'),f.inspected('cold'))['passed']


def test_native_inverse_norm_scale_multiplies_covariance(experiment):
    a=experiment.inspected('cold')
    np.testing.assert_array_equal(a['covariance'],np.diag([.25**2,(2/3)**2]))
    np.testing.assert_array_equal(a['correction'],[.25,2/3])


@pytest.mark.parametrize('run',['source','source_warm','warm','cold'])
def test_never_use_source_or_warm_or_same_execution_for_target_floor(experiment,run):
    with pytest.raises(ValueError,match='Floor|repeat'):
        check.compare(experiment.inspected('cold'),experiment.inspected('warm'),experiment.inspected(run))


@pytest.mark.parametrize('field,value',[
 ('nuisance_converged',False),('nuisance_floor_limited',True),('threshold_m',1e-6),('fixed_weights',False),
 ('dynamic_updates',True),('iterations',3),('maximum_update_m',.1)])
def test_strict_profile_required(experiment,field,value):
    change(experiment.runs['repeat']/'qr.profile.json',lambda v:v.update({field:value}));experiment.seal()
    with pytest.raises(ValueError):experiment.comparison()


@pytest.mark.parametrize('field,value',[('rank_status','unresolved'),('lambda',1e-3),('rank',1),('sigma_min',0.)])
def test_final_rank_and_damping_required(experiment,field,value):
    change(experiment.runs['warm']/'qr.3.diagnostics.json',lambda v:v.update({field:value}));experiment.seal()
    with pytest.raises(ValueError):experiment.comparison()


@pytest.mark.parametrize('field,value',[('status','running'),('returncode',1),('timed_out',True),('owned_process_group_cleaned',False)])
def test_execution_not_complete_rejected(experiment,field,value):
    change(experiment.runs['warm']/'execution.json',lambda v:v.update({field:value}))
    with pytest.raises(ValueError):experiment.comparison()


def test_supervisor_cleanliness_not_inferred_from_execution(experiment):
    change(experiment.runs['warm']/'supervisor.json',lambda v:v['cleanup'].update(verified=False));experiment.seal()
    with pytest.raises(ValueError,match='Supervisor'):experiment.comparison()


@pytest.mark.parametrize('artifact',['qr.3.R.bin','qr.2.parameters.tsv','diagnostic/residuals.gracefo1.xml'])
def test_missing_scientific_artifacts_rejected(experiment,artifact):
    (experiment.runs['warm']/artifact).unlink();experiment.seal()
    with pytest.raises(ValueError):experiment.comparison()


def test_extra_or_tampered_uninventoried_file_rejected(experiment):
    (experiment.runs['warm']/'extra').write_text('unexpected')
    with pytest.raises(ValueError,match='inventory'):experiment.comparison()


def test_input_tamper_detected(experiment):
    experiment.observation.write_text('changed support')
    with pytest.raises(ValueError,match='Pinned'):experiment.comparison()


def test_output_pin_detects_changed_rows(experiment):
    p=experiment.runs['warm']/'qr.3.rows.tsv';p.write_text(p.read_text().replace('0,1,2','0,1'))
    with pytest.raises(ValueError,match='Pinned'):experiment.comparison()


def test_supported_rows_change_even_with_refreshed_inventory(experiment):
    p=experiment.runs['warm']/'qr.3.rows.tsv';p.write_text(p.read_text().replace('0,1,2','0,1'));experiment.seal()
    with pytest.raises(ValueError,match='support'):experiment.comparison()


def test_same_repeat_physics_required(experiment):
    p=next(x for x in experiment.points if x['name']=='target_repeat');p['physical']['fixed_force.txt']['sha256']='f'*64
    prep=check.strict_json(experiment.preparation);prep['groups'][0]['points']=experiment.points;save(experiment.preparation,prep)
    change(experiment.freeze,lambda v:v.update(preparation=pin(experiment.preparation)));experiment.seal()
    with pytest.raises(ValueError,match='Physical'):experiment.comparison()


@pytest.mark.parametrize('key,value',[('context_sha256','f'*64),('chart_sha256','f'*64),('cold_origin_sha256','f'*64),
 ('source_generation','elsewhere/qr.3'),('export_status','ineligible'),('payload_sha256','f'*64)])
def test_seed_attribution_rejected(experiment,key,value):
    change(experiment.runs['warm']/'seed.bin.json',lambda v:v.update({key:value}));experiment.seal()
    with pytest.raises(ValueError):experiment.comparison()


def test_inherited_cold_seed_import_control_rejected(experiment):
    ex=experiment.runs['repeat']/'execution.json'
    change(ex,lambda v:v['effective_environment'].update(ORBIT_POC_NUISANCE_WARM_INPUT='other'))
    with pytest.raises(ValueError,match='controls'):experiment.comparison()


def test_donor_must_be_strict_even_if_companion_claims_eligible(experiment):
    change(experiment.runs['source']/'qr.profile.json',lambda v:v.update(nuisance_converged=False,nuisance_floor_limited=True));experiment.seal()
    with pytest.raises(ValueError,match='Strict'):experiment.comparison()


def test_cold_repeat_objective_floor_cannot_absorb_warm_failure(experiment):
    for name in ['warm']:
        change(experiment.runs[name]/'qr.3.profile.json',lambda v:v.update(direct_cost=6.,rhs2=12.))
    experiment.seal();result=experiment.comparison()
    assert not result['passed'] and not result['checks']['objective_within_cold_floor']
    assert result['cold_objective_floor']==8*np.finfo(float).eps*5.


@pytest.mark.parametrize('kind,value', [('code',.003),('phase',.00003)])
def test_one_percent_prediction_limit_is_strict(experiment,kind,value):
    experiment.residual(experiment.runs['warm'],**{kind:value});experiment.seal()
    result=experiment.comparison();assert not result['passed']
    assert not result['checks'][kind+'_prediction_below_one_percent_noise']


def test_changed_weights_rejected(experiment):
    experiment.residual(experiment.runs['repeat'],sigma=.004);experiment.seal()
    with pytest.raises(ValueError,match='weights'):experiment.comparison()


def test_nonzero_code_and_tec_penalties_required(experiment):
    p=experiment.runs['warm']/'qr.3.rows.tsv';p.write_text(p.read_text().replace('code_bias_full_constraint\t1\t','code_bias_full_constraint\t0\t'));experiment.seal()
    with pytest.raises(ValueError,match='full-prior'):experiment.comparison()


def test_inert_comparison_preserves_scientific_fields(experiment):
    change(experiment.runs['cold']/'qr.1.nuisance_line_search.json',lambda v:v['trials'][0].update(actual_reduction=2.));experiment.seal()
    result=check.inert(experiment.inspected('disabled'),experiment.inspected('cold'))
    assert not result['passed'] and result['changed_artifacts']==['qr.1.nuisance_line_search.json']


def test_inert_ignores_only_declared_cpu_and_rss(experiment):
    change(experiment.runs['cold']/'qr.1.nuisance_line_search.json',lambda v:v['trials'][0].update(child_user_seconds=100.,peak_child_rss_bytes=200));experiment.seal()
    assert check.inert(experiment.inspected('disabled'),experiment.inspected('cold'))['passed']


def test_inert_cannot_be_two_enabled_runs(experiment):
    with pytest.raises(ValueError,match='disabled'):check.inert(experiment.inspected('cold'),experiment.inspected('cold'))


def test_diagnostic_covariance_failure_is_not_accepted_covariance(experiment):
    matrix(experiment.runs['warm']/'qr.3.R.bin',[[2.001,0],[0,3]]);experiment.seal()
    result=experiment.comparison();assert not result['passed']
    assert not result['checks']['unit_normalized_dynamic_covariance_relative_below_1e8']
    assert 'no accepted orbit covariance' in result['covariance_scope'].lower()


def test_duplicate_nonfinite_json_rejected(tmp_path):
    p=tmp_path/'bad';p.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError,match='Duplicate'):check.strict_json(p)
    p.write_text('{"a":1e999}')
    with pytest.raises(ValueError,match='Nonfinite'):check.strict_json(p)


def test_cli_missing_run_preserves_failed_report(tmp_path,monkeypatch):
    import sys
    output=tmp_path/'result.json';monkeypatch.setattr(sys,'argv',[str(SCRIPT),str(tmp_path/'missing'),str(tmp_path/'missing2'),'--inert','--output',str(output)])
    assert check.main()==1
    result=check.strict_json(output)
    assert result['passed'] is False and result['accepted_orbit_covariance'] is False and 'error' in result


def test_runtime_library_alias_uses_content_pin_but_seed_alias_rejected(experiment):
    library=experiment.root/'library-real';library.write_bytes(b'library')
    alias=experiment.root/'library.so';alias.symlink_to(library)
    build=check.strict_json(experiment.build);build['libraries']=[pin(alias)];save(experiment.build,build)
    change(experiment.freeze,lambda v:v.update(build_record=pin(experiment.build)));experiment.seal()
    assert experiment.comparison()['passed']
    payload=experiment.runs['warm']/'seed.bin';target=experiment.root/'payload';payload.rename(target);payload.symlink_to(target)
    experiment.seal()
    with pytest.raises(ValueError,match='symlink'):experiment.comparison()


def test_supervisor_plan_limits_cannot_be_changed(experiment):
    path=experiment.runs['warm']/'supervisor.plan.json';change(path,lambda v:v.update(timeout_seconds=901))
    change(experiment.runs['warm']/'supervisor.json',lambda v:v.update(plan_sha256=check.digest(path)));experiment.seal()
    with pytest.raises(ValueError,match='limits'):experiment.comparison()


def test_configuration_cannot_change_frozen_prepared_threshold(experiment):
    root=experiment.runs['warm'];xml=ET.parse(root/'config.xml');ET.SubElement(xml.getroot().find('.//orbitPocNumerics'),'nuisanceThreshold').text='1e-6';xml.write(root/'config.xml')
    next(j for j in experiment.jobs if j['id']=='warm')['profile_sha256']=check.digest(root/'config.xml');experiment.seal()
    with pytest.raises(ValueError,match='prepared scientific'):experiment.comparison()


def test_native_nan_redundancy_is_diagnostic_only(experiment):
    path=experiment.runs['warm']/'diagnostic/residuals.gracefo1.xml';xml=ET.parse(path)
    cells=xml.getroot().find('.//observation').findall('cell');cells[6].text=cells[9].text='nan';xml.write(path);experiment.seal()
    assert experiment.comparison()['passed']


def test_native_all_nan_unused_slot_stays_in_support(experiment):
    for name in ('cold','warm','repeat'):
        path=experiment.runs[name]/'diagnostic/residuals.gracefo1.xml';xml=ET.parse(path);epoch=xml.getroot().find('.//epoch')
        for key,values in [('type',['C2WG']*3),('observation',['nan']*3)]:
            node=epoch.find(key);node.find('count').text=str(int(node.findtext('count'))+3)
            for value in values:ET.SubElement(node,'cell').text=value
        xml.write(path)
    experiment.seal();result=experiment.comparison();assert result['passed'] and result['absent_prediction_slots']==1
    path=experiment.runs['warm']/'diagnostic/residuals.gracefo1.xml';xml=ET.parse(path)
    cells=xml.getroot().find('.//observation').findall('cell');cells[-3].text='0';cells[-1].text='.3';xml.write(path);experiment.seal()
    with pytest.raises(ValueError,match='weights'):experiment.comparison()


@pytest.mark.parametrize('index',[5,7,8,10])
def test_partial_nan_physical_measurements_rejected(experiment,index):
    path=experiment.runs['warm']/'diagnostic/residuals.gracefo1.xml';xml=ET.parse(path)
    xml.getroot().find('.//observation').findall('cell')[index].text='nan';xml.write(path);experiment.seal()
    with pytest.raises(ValueError,match='residual/weight'):experiment.comparison()


@pytest.mark.parametrize('field,value',[('inputs_unchanged',False),('inputs_unchanged',1),('identity_error','changed'),('blocked_reason','failed donor')])
def test_execution_verified_identity_required(experiment,field,value):
    change(experiment.runs['warm']/'execution.json',lambda v:v.update({field:value}))
    with pytest.raises(ValueError,match='input identity'):experiment.comparison()


@pytest.mark.parametrize('section,key,value',[
    ('eligibility','nuisance_converged',1),('eligibility','nuisance_floor_limited',0),('eligibility','fresh_undamped',1),
    ('invariants','target_cold_ionosphere_unchanged',1),('invariants','target_clock_prior_anchors_unchanged',1),
    ('imported','used',1)])
def test_seed_integer_flags_do_not_count_as_boolean_evidence(experiment,section,key,value):
    change(experiment.runs['warm']/'seed.bin.json',lambda v:v[section].update({key:value}));experiment.seal()
    with pytest.raises(ValueError,match='boolean'):experiment.comparison()


def test_hash_read_atime_change_is_not_content_mutation(tmp_path,monkeypatch):
    from types import SimpleNamespace
    path=tmp_path/'runtime';path.write_bytes(b'fixed runtime');record=pin(path)
    original=Path.stat;calls=[0]
    def stat_with_read_atime(self,*args,**kwargs):
        value=original(self,*args,**kwargs)
        if self!=path:return value
        calls[0]+=1
        fields={key:getattr(value,key) for key in dir(value) if key.startswith('st_')}
        fields['st_atime']+=calls[0];fields['st_atime_ns']+=calls[0]*1000000000
        return SimpleNamespace(**fields)
    monkeypatch.setattr(Path,'stat',stat_with_read_atime)
    assert check.pin(record)==path and calls[0]>1
