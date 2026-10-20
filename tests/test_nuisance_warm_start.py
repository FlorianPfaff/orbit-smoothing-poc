"""Offline lifecycle tests: opaque seeds never replace numerical validation."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.numerics import backend
from orbit_poc.numerics.nuisance_warm_start import WarmStartLifecycle, without_inherited_warm_environment, PREFIX
from orbit_poc.numerics.optimizer import Linearization, NumericalFailure


def write_json(path, value):
    Path(path).write_text(json.dumps(value))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lifecycle(tmp_path, **changes):
    tmp_path.mkdir(exist_ok=True)
    native = tmp_path/'native';native.write_bytes(b'pinned native executable')
    data = tmp_path/'observations';data.write_bytes(b'pinned observation weights and support')
    item={'path':str(data),'sha256':digest(data),'role':'gnss_observations'}
    job={'estimation_inputs':[item],'expected_native_binary_sha256':digest(native),
         'method':'groops_pulses','parameters':{'interval_seconds':1200.,'sigma_velocity_m_s':1e-4},
         'source_hash':'a'*64,'mask_hash':'b'*64,'preprocessing_hash':'c'*64}
    job.update(changes)
    root=tmp_path/'fit';root.mkdir()
    return WarmStartLifecycle(job,{'native_artifacts':[item]},native,root,
        environment={PREFIX+'_STARTS':'1'}),job


def evaluated(life, name, *, limited=False, support='support', mutate=None, tighter=False, covariance=False):
    folder=life.root/name;folder.mkdir()
    label=name.split('-',2)[2]
    environment,plan=life.profile(folder,label,tighter=tighter,covariance=covariance)
    point=Linearization(np.eye(2),np.zeros(2),np.ones(2),np.array([True,False]),4,1.,0.,support,
        backend.PhysicalState(np.zeros(6),np.zeros(3),folder/'orbit.dat'),
        metadata={'folder':str(folder),'factor_prefix':str(folder/'qr.3'),
                  'nuisance_floor_limited':limited})
    profile={'nuisance_converged':not limited,'nuisance_floor_limited':limited}
    diagnostics={'lambda':0.,'rank_status':'full'}
    value={'schema':'orbit-poc-native-nuisance-warm-state-v1','mode':life.mode,'context_sha256':life.context,
           'chart_sha256':'1'*64,'cold_origin_sha256':'2'*64,'source_prefix':str(folder/'qr'),
           'source_generation':str(folder/'qr.3'),'eligibility':{'nuisance_converged':not limited,
              'nuisance_floor_limited':limited,'fresh_undamped':True,'rank_status':'full'},
           'imported':{'used':plan.donor is not None,'path':plan.donor.payload.path if plan.donor else '',
                       'sha256':plan.donor.payload.sha256 if plan.donor else ''},
           'counts':{'coordinates':20},'invariants':{'target_cold_ionosphere_unchanged':True,
              'target_clock_prior_anchors_unchanged':True},'export_status':'ineligible' if limited else 'exported',
           'payload_sha256':None}
    if not limited:
        plan.output.write_bytes(b'opaque native serialized coordinates '+name.encode())
        value['payload_sha256']=digest(plan.output)
    if mutate:mutate(value,point,diagnostics)
    write_json(str(plan.output)+'.json',value)
    life.capture(point,plan,profile,diagnostics)
    return point,environment,plan


def install(life,point):
    life.commit_accept(life.prepare_accept(point))


def test_disabled_is_compatible_without_inputs_or_native(tmp_path):
    life=WarmStartLifecycle({}, {}, '/missing/native',tmp_path,environment={})
    assert not life.enabled and life.context is None
    assert life.profile(tmp_path,'trial-001')==({},None)
    life.capture(None,None,None,None)
    assert life.prepare_accept(None) is None


@pytest.mark.parametrize('flag',['true','2','',1,True])
def test_invalid_feature_flags_fail(tmp_path,flag):
    with pytest.raises(ValueError,match='WARM_STARTS'):
        WarmStartLifecycle({}, {}, '/missing/native',tmp_path,environment={PREFIX+'_STARTS':flag})


def test_unsupported_mode_fails_only_when_enabled(tmp_path):
    with pytest.raises(ValueError,match='mode'):
        WarmStartLifecycle({}, {}, '/missing/native',tmp_path,
            environment={PREFIX+'_STARTS':'1',PREFIX+'_MODE':'arbitrary'})
    assert not WarmStartLifecycle({}, {}, '/missing/native',tmp_path,
        environment={PREFIX+'_STARTS':'0',PREFIX+'_MODE':'arbitrary'}).enabled


def test_only_accept_promotes_and_rejected_candidate_cannot_replace(tmp_path):
    life,_=lifecycle(tmp_path)
    initial,_,_=evaluated(life,'point-001-initial')
    assert life.donor is None
    install(life,initial);original=life.donor
    rejected,env,_=evaluated(life,'point-002-trial-001')
    assert env[PREFIX+'_INPUT']==original.payload.path and life.donor is original
    _,env,_=evaluated(life,'point-003-trial-002')
    assert env[PREFIX+'_INPUT']==original.payload.path
    install(life,rejected)
    assert life.donor.payload.path.endswith('point-002-trial-001/nuisance-warm-state.bin')


@pytest.mark.parametrize('label,tighter,covariance',[
    ('initial',False,False),('repeat',False,False),('closure-refinement',True,False),
    ('repeat-floor',False,False),('refine-floor',True,False),('confirmation',True,False),
    ('final-covariance',True,True),('trial-001',True,False),('trial-001',False,True),
    ('trial-1',False,False),('trial-000',False,False),('trial-001-extra',False,False)])
def test_protected_evaluations_never_import(tmp_path,label,tighter,covariance):
    life,_=lifecycle(tmp_path);p,_,_=evaluated(life,'point-001-initial');install(life,p)
    folder=life.root/'next';folder.mkdir()
    env,plan=life.profile(folder,label,tighter=tighter,covariance=covariance)
    assert PREFIX+'_INPUT' not in env and PREFIX+'_INPUT_SHA256' not in env and plan.donor is None
    assert env[PREFIX+'_OUTPUT']  # Eligible cold results can be donors only after acceptance.


def test_accepted_floor_limited_point_revokes_donor(tmp_path):
    life,_=lifecycle(tmp_path);p,_,_=evaluated(life,'point-001-initial');install(life,p)
    floor,_,_=evaluated(life,'point-002-trial-001',limited=True)
    assert life.donor is not None
    install(life,floor)
    assert life.donor is None
    folder=life.root/'next';folder.mkdir()
    assert PREFIX+'_INPUT' not in life.profile(folder,'trial-002')[0]


@pytest.mark.parametrize('alter',[
    lambda v,p,d:v.update(payload_sha256='f'*64),
    lambda v,p,d:v.update(context_sha256='f'*64),
    lambda v,p,d:v.update(mode='receiver_clock_v1'),
    lambda v,p,d:v.update(source_generation='wrong'),
    lambda v,p,d:v.update(source_prefix='wrong'),
    lambda v,p,d:v.update(chart_sha256='unknown'),
    lambda v,p,d:v.update(export_status='ineligible'),
    lambda v,p,d:v['counts'].update(coordinates=0),
    lambda v,p,d:v['eligibility'].update(fresh_undamped=False),
    lambda v,p,d:v['invariants'].update(target_clock_prior_anchors_unchanged=False),
    lambda v,p,d:v['invariants'].update(target_cold_ionosphere_unchanged=False),
    lambda v,p,d:v['imported'].update(used=True),
    lambda v,p,d:d.update(rank_status='unresolved'),
    lambda v,p,d:d.update(**{'lambda':1.}),
])
def test_invalid_export_is_not_promoted(tmp_path,alter):
    life,_=lifecycle(tmp_path)
    with pytest.raises(ValueError):evaluated(life,'point-001-initial',mutate=alter)
    assert life.donor is None and life.pending=={}


@pytest.mark.parametrize('target',['payload','companion'])
@pytest.mark.parametrize('action',['missing','changed','symlink','same_bytes_new_identity'])
def test_seed_identity_is_rechecked_at_accept_and_load(tmp_path,target,action):
    life,_=lifecycle(tmp_path);point,_,_=evaluated(life,'point-001-initial')
    candidate=life.pending[point.metadata['folder']][0]
    path=Path(getattr(candidate,target).path);raw=path.read_bytes()
    if action=='missing':path.unlink()
    elif action=='changed':path.write_bytes(raw+b'changed')
    elif action=='symlink':
        other=path.with_name('other');other.write_bytes(raw);path.unlink();path.symlink_to(other)
    else:
        path.unlink();path.write_bytes(raw)
    with pytest.raises((OSError,ValueError)):life.prepare_accept(point)
    life.donor=candidate
    folder=life.root/'next';folder.mkdir()
    with pytest.raises((OSError,ValueError)):life.profile(folder,'trial-001')


def test_candidate_with_changed_support_cannot_change_donor(tmp_path):
    life,_=lifecycle(tmp_path);point,_,_=evaluated(life,'point-001-initial');install(life,point);original=life.donor
    with pytest.raises(ValueError,match='support'):evaluated(life,'point-002-trial-001',support='different')
    assert life.donor is original


def test_changed_accepted_physical_values_rejected(tmp_path):
    life,_=lifecycle(tmp_path);point,_,_=evaluated(life,'point-001-initial');point.state.force[0]=1.
    with pytest.raises(ValueError,match='identity changed'):life.prepare_accept(point)


def test_unregistered_point_cannot_be_accepted(tmp_path):
    life,_=lifecycle(tmp_path);p,_,_=evaluated(life,'point-001-initial')
    other=replace(p,metadata={**p.metadata,'folder':str(life.root/'foreign')})
    with pytest.raises(ValueError,match='no validated'):life.prepare_accept(other)


def test_base_input_mutation_blocks_seed_use(tmp_path):
    life,job=lifecycle(tmp_path);point,_,_=evaluated(life,'point-001-initial');install(life,point)
    Path(job['estimation_inputs'][0]['path']).write_bytes(b'new data')
    folder=life.root/'next';folder.mkdir()
    with pytest.raises(ValueError,match='identity changed'):life.profile(folder,'trial-001')


def test_scientific_context_changes_with_weights_settings(tmp_path):
    a,_=lifecycle(tmp_path/'a');b,_=lifecycle(tmp_path/'b',parameters={'interval_seconds':600.,'sigma_velocity_m_s':1e-4})
    assert a.context!=b.context


def test_context_excludes_output_paths_and_transient_job_id(tmp_path):
    a,_=lifecycle(tmp_path/'a',id='first',job_sha256='d'*64)
    b,_=lifecycle(tmp_path/'b',id='second',job_sha256='e'*64)
    assert a.context==b.context


def test_output_collision_is_not_overwritten(tmp_path):
    life,_=lifecycle(tmp_path);folder=life.root/'next';folder.mkdir();(folder/'nuisance-warm-state.bin').write_bytes(b'old')
    with pytest.raises(ValueError,match='overwrite'):life.profile(folder,'initial')


def test_environment_guard_clears_all_fields_and_restores_after_failure(monkeypatch):
    fields={PREFIX+'_STARTS':'1',PREFIX+'_INPUT':'untrusted',PREFIX+'_MODE':'untrusted',
            PREFIX+'_CONTEXT_SHA256':'untrusted',PREFIX+'_FUTURE':'untrusted'}
    for key,value in fields.items():monkeypatch.setenv(key,value)
    with pytest.raises(RuntimeError):
        with without_inherited_warm_environment():
            assert not any(key.startswith(PREFIX) for key in os.environ)
            os.environ[PREFIX+'_OUTPUT']='temporary'
            raise RuntimeError('failed native call')
    assert all(os.environ[k]==v for k,v in fields.items()) and PREFIX+'_OUTPUT' not in os.environ


def test_native_execute_does_not_pass_inherited_seed(monkeypatch,tmp_path):
    monkeypatch.setenv(PREFIX+'_STARTS','1');monkeypatch.setenv(PREFIX+'_INPUT','untrusted')
    model=backend.NativeModel.__new__(backend.NativeModel)
    model.binary=tmp_path/'native';model.controls=SimpleNamespace(wall_time_seconds=7200.)
    model.start=time.monotonic();model.executions=[]
    def fake(*args,**kwargs):
        assert not any(key.startswith(PREFIX) for key in os.environ)
        assert kwargs['environment_overrides']=={'controlled':'value'}
        return {'returncode':0}
    monkeypatch.setattr(backend.native,'run_native',fake)
    model.execute(ET.Element('groops'),tmp_path/'propagate','propagate',{'controlled':'value'})
    assert os.environ[PREFIX+'_INPUT']=='untrusted' and model.executions==[{'returncode':0}]


def test_rank_failure_in_accept_preserves_old_donor(monkeypatch,tmp_path):
    life,_=lifecycle(tmp_path);initial,_,_=evaluated(life,'point-001-initial');install(life,initial);old=life.donor
    candidate,_,_=evaluated(life,'point-002-trial-001');candidate.factor[1,1]=0.
    model=backend.NativeModel.__new__(backend.NativeModel);model.warm_start=life;model.root=life.root;model.protected_factor=None
    monkeypatch.setattr(backend,'discard_inactive_factors',lambda *a,**k:None)
    with pytest.raises(NumericalFailure,match='rank_deficient'):model.accept(candidate)
    assert life.donor is old and model.protected_factor is None


def test_retention_failure_in_accept_preserves_old_donor(monkeypatch,tmp_path):
    life,_=lifecycle(tmp_path);initial,_,_=evaluated(life,'point-001-initial');install(life,initial);old=life.donor
    candidate,_,_=evaluated(life,'point-002-trial-001')
    model=backend.NativeModel.__new__(backend.NativeModel);model.warm_start=life;model.root=life.root;model.protected_factor=None
    def fail(*a,**k):raise OSError('retention failure')
    monkeypatch.setattr(backend,'discard_inactive_factors',fail)
    with pytest.raises(OSError):model.accept(candidate)
    assert life.donor is old and model.protected_factor is None


def test_direct_segmented_exporter_clears_inherited_seed(monkeypatch,tmp_path):
    from orbit_poc.segmented import backend as segmented
    monkeypatch.setenv(PREFIX+'_STARTS','1');monkeypatch.setenv(PREFIX+'_INPUT','untrusted')
    native=tmp_path/'native';native.write_bytes(b'exporter')
    source=tmp_path/'source.xml';source.write_text('<groops/>')
    model=segmented.V4Model.__new__(segmented.V4Model);model.root=tmp_path
    model.job={'backend':{'diagnostic_native':{'path':str(native),'sha256':digest(native)}}}
    model.controls=SimpleNamespace(wall_time_seconds=7200.);model.start=time.monotonic()
    final=SimpleNamespace(metadata={'source':str(source),'config':{'native_paths':{'variational':'unused'},'date':'2024-05-10'}})
    monkeypatch.setattr(backend.NativeModel,'_evaluation',lambda *a,**k:[ET.Element('OrbitPocEvaluateVariational')])
    monkeypatch.setattr(segmented,'_standalone',lambda *a:ET.Element('groops'))
    def stopped(*a,**k):
        assert not any(key.startswith(PREFIX) for key in os.environ)
        raise RuntimeError('stopped before native execution')
    monkeypatch.setattr(segmented.native,'run_native',stopped)
    with pytest.raises(RuntimeError,match='stopped before'):model._dense_covariance_extras(final,np.zeros(1))
    assert os.environ[PREFIX+'_INPUT']=='untrusted'


def test_scientific_job_mutation_blocks_next_profile(tmp_path):
    life,job=lifecycle(tmp_path);p,_,_=evaluated(life,'point-001-initial');install(life,p)
    job['parameters']['sigma_velocity_m_s']=1.
    folder=life.root/'next';folder.mkdir()
    with pytest.raises(ValueError,match='job/preparation changed'):life.profile(folder,'trial-001')


def test_post_native_segmented_graph_failure_does_not_install_candidate(monkeypatch,tmp_path):
    from orbit_poc.segmented import backend as segmented
    life,_=lifecycle(tmp_path);p,_,_=evaluated(life,'point-001-initial');install(life,p);old=life.donor
    candidate,_,_=evaluated(life,'point-002-trial-001')
    candidate.metadata['design']=str(Path(candidate.metadata['folder'])/'design.txt')
    model=segmented.V4Model.__new__(segmented.V4Model);model.segmented=True;model.segment_seconds=3600
    monkeypatch.setattr(backend.NativeModel,'evaluate',lambda *a,**k:candidate)
    def failed(*a,**k):raise NumericalFailure('changed_support','post-native graph rejected')
    monkeypatch.setattr(segmented,'build_graph',failed)
    with pytest.raises(NumericalFailure,match='graph rejected'):model.evaluate(candidate.state,'trial-001')
    assert life.donor is old
