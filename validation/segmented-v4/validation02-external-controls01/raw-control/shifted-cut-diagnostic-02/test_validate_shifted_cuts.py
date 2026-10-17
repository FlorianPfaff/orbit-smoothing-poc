import importlib.util
from pathlib import Path
from dataclasses import replace
import json,struct
import numpy as np
import pytest
from test_segmented_graph import exported_problem
from orbit_poc.numerics.optimizer import proposal, selected_covariance
from orbit_poc.comparison.protocol import artifact_record, write_json

@pytest.fixture
def helper():
    spec=importlib.util.spec_from_file_location('shifted_diagnostic',Path(__file__).with_name('validate_shifted_cuts.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def pin(path):return {'path':str(path),'sha256':__import__('hashlib').sha256(path.read_bytes()).hexdigest()}

def sealed_pipeline(helper,tmp_path):
    v=tmp_path/'validation.json';write_json(v,{'schema':'orbit-poc-segmented-linearization-gate-v1','passed':True,'physical_evaluations':1})
    execution=tmp_path/'execution.json';write_json(execution,{'status':'complete','returncode':0,'harness_execution':{'owned_process_group_cleaned':True}})
    steps=[{'name':n,'status':'passed','execution':pin(execution)} for n in helper.STAGES]
    steps[-2]['evidence']={'result':pin(v)}
    p=tmp_path/'pipeline.json';write_json(p,{'status':'passed','steps':steps})
    c=tmp_path/'controller.json';write_json(c,{'status':'passed','final_cleanup':{'verified':True},'cli_validation':{'pipeline':pin(p)}})
    return c,p,v

def test_actual_evidence_nesting_and_all14_cleanup_required(helper,tmp_path):
    c,p,v=sealed_pipeline(helper,tmp_path);assert helper.terminal_gate(pin(c),pin(p),pin(v))['passed']

@pytest.mark.parametrize('change',['controller_running','cleanup','pipeline_running','stage_missing','stage_order','process_failure','foreign_gate','duplicate_gate'])
def test_terminal_guard_refuses_partial_or_misattributed_gates(helper,tmp_path,change):
    c,p,v=sealed_pipeline(helper,tmp_path);a=json.loads(c.read_text());b=json.loads(p.read_text())
    if change=='controller_running':a['status']='running'
    elif change=='cleanup':a['final_cleanup']['verified']=False
    elif change=='pipeline_running':b['status']='running'
    elif change=='stage_missing':b['steps'].pop()
    elif change=='stage_order':b['steps'].reverse()
    elif change=='process_failure':
        e=tmp_path/'execution.json';x=json.loads(e.read_text());x['returncode']=1;write_json(e,x)
        for s in b['steps']:s['execution']=pin(e)
    elif change=='foreign_gate':b['steps'][-2]['evidence']['result']['path']=str(tmp_path/'other.json')
    elif change=='duplicate_gate':b['steps'][-1]['evidence']=b['steps'][-2]['evidence']
    write_json(p,b);a['cli_validation']['pipeline']=pin(p);write_json(c,a)
    with pytest.raises(ValueError):helper.terminal_gate(pin(c),pin(p),pin(v))

def test_ledger_identity_excludes_only_elimination_groups(helper,tmp_path):
    point,paths=exported_problem(tmp_path,local_forcing=True,wide_halo=True)
    graph,_=helper.build_graph(point,*paths,segment_seconds=3600)
    shifted,_=helper.build_graph(point,*paths,segment_seconds=3600,segment_offset_seconds=1800)
    assert graph.groups!=shifted.groups and helper.ledger_identity(graph)==helper.ledger_identity(shifted)
    assert helper.interior_movement(graph,shifted,16,600.)['adequate']
    row=shifted.stochastic[0];changed=replace(shifted,stochastic=(replace(row,rhs=row.rhs+1),*shifted.stochastic[1:]))
    assert helper.ledger_identity(changed)!=helper.ledger_identity(graph)
    assert not helper.interior_movement(graph,graph,16,600.)['adequate']


def install_solver_stub(helper,monkeypatch,*,fault=None):
    class FakeSystem:
        def __init__(self,graph,solver,directory,deadline=None):
            self.graph=graph;self.calls=[];self.directory=Path(directory);self.directory.mkdir()
        def validate(self,point):pass
    def proposed(point,damping):
        dense=replace(point,linear_system=None);step,pred,gradient=proposal(dense,damping)
        if point.linear_system is not None:
            z=step/point.scales;energy=float(np.linalg.norm(point.rhs-point.factor@z)**2+point.residual_energy+damping*np.linalg.norm(z[point.dynamic])**2)
            payload={'residual_energy':energy,'orthogonal_residual_energy':energy,'equality_max_backward_error':0.}
            if fault in payload:payload[fault]=float('nan') if fault=='equality_max_backward_error' else energy+1.
            folder=point.linear_system.directory;p=folder/f'{len(point.linear_system.calls)}.json';write_json(p,payload)
            point.linear_system.calls.append({'output':str(p)})
            if fault=='map':step=step+1
        return step,pred,gradient
    def cov(point,design):
        value=selected_covariance(replace(point,linear_system=None),design)
        return value*2 if point.linear_system is not None and fault=='covariance' else value
    monkeypatch.setattr(helper,'SegmentedLinearSystem',FakeSystem);monkeypatch.setattr(helper,'proposal',proposed);monkeypatch.setattr(helper,'selected_covariance',cov)


def test_four_shift_profiles_use_fixed_ledgers_and_undamped_covariance(helper,tmp_path,monkeypatch):
    point,paths=exported_problem(tmp_path,local_forcing=True,wide_halo=False)
    # Localize the first forcing coefficient before1800s; the original fixture
    # ends that forcing near3600s and correctly cannot cover a4h/1800s cut.
    records=[json.loads(line) for line in paths[0].read_text().splitlines()]
    for row in records:
        if row['kind']=='forcing':
            for term in row['integrand']:
                if term[1]==0 and row['index']>=2:term[2]=0.
    paths[0].write_text(''.join(json.dumps(r)+'\n' for r in records))
    gate_path=Path(__import__('test_segmented_graph').__file__).parents[1]/'scripts/validate_segmented_linearization.py'
    spec=importlib.util.spec_from_file_location('unchanged_oracle',gate_path);gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    graph,_=helper.build_graph(point,*paths,segment_seconds=3600)
    a,b,_=gate.original_weighted_rows(graph);scales=1/np.linalg.norm(a,axis=0);q,r=np.linalg.qr(a*scales)
    point=replace(point,factor=r,rhs=q.T@b,scales=scales,effective_rows=len(b),residual_energy=float(np.linalg.norm(b-q@(q.T@b))**2))
    install_solver_stub(helper,monkeypatch)
    r=helper.compare(point,paths,tmp_path/'solver',tmp_path/'result')
    assert len(r['profiles'])==4 and r['coverage_adequate']
    assert {(p['segment_seconds'],p['segment_offset_seconds']) for p in r['profiles']}=={(3600,300.),(3600,1800.),(14400,300.),(14400,1800.)}
    for p in r['profiles']:
        assert [t['damping'] for t in p['trials']]==[0.,.001,1000.] and p['covariance_optimization_damping']==0.
        assert p['numerically_equivalent']
    assert r['physical_evaluations']==r['nuisance_profile_evaluations']==0
    assert 'unit denominator' in r['gradient_scope'] and 'not the original' in r['gradient_scope']
    assert all('dense_scaled_gradient' not in t and 'dense_gradient_unit_denominator' in t for p in r['profiles'] for t in p['trials'])


def test_global_parameters_do_not_fabricate_interior_coverage(helper,tmp_path,monkeypatch):
    point,paths=exported_problem(tmp_path);install_solver_stub(helper,monkeypatch)
    r=helper.compare(point,paths,tmp_path/'solver',tmp_path/'result')
    assert r['numerically_equivalent'] and not r['coverage_adequate']
    assert all(p['status']=='equivalent_without_interior_coverage' for p in r['profiles'])

@pytest.mark.parametrize('fault',['map','residual_energy','orthogonal_residual_energy','equality_max_backward_error','covariance'])
def test_changed_numerics_fail_closed_with_progress(helper,tmp_path,monkeypatch,fault):
    point,paths=exported_problem(tmp_path);install_solver_stub(helper,monkeypatch,fault=fault)
    with pytest.raises(ValueError):helper.compare(point,paths,tmp_path/'solver',tmp_path/'result')
    assert json.loads((tmp_path/'result/progress.json').read_text())['profiles']


def test_fresh_output_and_pin_tamper_are_refused(helper,tmp_path):
    p=tmp_path/'p.json';p.write_text('{}');old=pin(p);p.write_text('{"x":1}')
    with pytest.raises(ValueError,match='Artifact changed'):helper.checked(old)
    folder=tmp_path/'occupied';folder.mkdir();(folder/'old').write_bytes(b'preserved')
    with pytest.raises(ValueError,match='fresh'):helper.compare(None,None,None,folder)
    assert (folder/'old').read_bytes()==b'preserved'


def captured(helper,tmp_path):
    point,paths=exported_problem(tmp_path)
    prefix=point.metadata['factor_prefix'];info={'scales':point.scales.tolist(),'dynamic':point.dynamic.tolist(),'orthogonal_energy':point.residual_energy}
    def matrix(path,a):
        a=np.asarray(a).reshape((len(a),-1));Path(path).write_bytes(struct.pack('<QQ',*a.shape)+np.asarray(a,dtype='<f8').tobytes())
    matrix(prefix+'.R.bin',point.factor);matrix(prefix+'.rhs.bin',point.rhs)
    write_json(prefix+'.factor.json',info);write_json(prefix+'.diagnostics.json',{'reduced_rows':point.effective_rows});Path(prefix+'.parameters.tsv').write_text('fixture-only metadata; production graph validates this')
    source=tmp_path/'source.json';source.write_text('{}');native=tmp_path/'native';native.write_text('binary');solver=tmp_path/'solver';solver.write_text('solver');req=tmp_path/'request.json';req.write_text('{}')
    covariance=selected_covariance(point,np.eye(len(point.scales)));dense=tmp_path/'dense.npz';np.savez_compressed(dense,covariance=covariance,posterior_sd=np.sqrt(np.diag(covariance)),factor=point.factor,rhs=point.rhs,scales=point.scales,dynamic=point.dynamic)
    ar=lambda role,p:artifact_record(role,p)
    v={'source_sha256':'source','source':pin(source),'native':pin(native),'solver':pin(solver),'request':pin(req),'original_request':pin(req),
       'captured_exports':[ar(k,p) for k,p in zip(('native_variation_design','native_weighted_rows','native_local_observation_design'),paths)],
       'native_evidence':[ar('native_factor',prefix+'.factor.json'),ar('native_rank',prefix+'.diagnostics.json')],
       'comparison':{'dense_reference':ar('dense',dense),'dense_orthogonal_residual_energy':point.residual_energy,'effective_rows':point.effective_rows,'support_hash':point.support_hash,'linearization_sha256':helper.linearization_digest(point)}}
    return point,v,solver


def test_reconstructs_same_native_factor_without_evaluating_physics(helper,tmp_path,monkeypatch):
    point,v,solver=captured(helper,tmp_path);monkeypatch.setattr(helper,'source_snapshot',lambda source:{'sha256':'source'})
    restored,paths,supp=helper.load_captured(v,tmp_path,'source',solver,pin(solver)['sha256'])
    assert helper.linearization_digest(restored)==helper.linearization_digest(point)
    assert restored.state is None and restored.objective==0. and len(supp)==3

@pytest.mark.parametrize('change',['factor','scales','energy','digest','source','solver','role'])
def test_capture_reload_rejects_changed_attribution(helper,tmp_path,monkeypatch,change):
    point,v,solver=captured(helper,tmp_path);monkeypatch.setattr(helper,'source_snapshot',lambda source:{'sha256':'source'})
    if change=='factor':Path(point.metadata['factor_prefix']+'.R.bin').write_bytes(b'broken')
    elif change in ('scales','energy'):
        path=Path(point.metadata['factor_prefix']+'.factor.json');x=json.loads(path.read_text());x['scales'][0]*=2 if change=='scales' else 1;x['orthogonal_energy']+=1 if change=='energy' else 0;write_json(path,x);v['native_evidence'][0]=artifact_record('native_factor',path)
    elif change=='digest':v['comparison']['linearization_sha256']='wrong'
    elif change=='source':v['source_sha256']='wrong'
    elif change=='solver':solver.write_bytes(b'changed')
    elif change=='role':v['captured_exports'].reverse()
    with pytest.raises(ValueError):helper.load_captured(v,tmp_path,'source',solver,pin(solver)['sha256'])
