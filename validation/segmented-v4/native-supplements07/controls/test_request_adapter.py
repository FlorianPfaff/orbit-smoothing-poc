"""Pure synthetic control fixtures only; never actual native launch evidence."""
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
import gates as g
import request_adapter as a
from test_gates import xml

C=Path('/mnt/d/orbit-segmented-v4/control')


def write(path,value):
    path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());return a.pin(path)


def fixture_xml():
    return xml().replace(b'</groops>',b'<program><FileConvert><inputfile>/old/orbit.txt</inputfile><outputfile>/old/orbit-table.txt</outputfile></FileConvert></program></groops>')


def make(tmp_path):
    root=tmp_path/'inputs';root.mkdir();out=tmp_path/'output'
    def save(name,value):return write(root/name,value)
    native=save('native',b'not executable');initial=save('physical_initial.txt',b'fixed')
    att=save('attitude.txt',b'not native');reference=save('orbit.txt',b'retained final orbit')
    source=save('source.cpp',b'source');decoder=save('decoder.py',b'decoder')
    identity={'full_source_sha256':'a'*64,'comparison_source_sha256':'b'*64,'native_sha256':native['sha256'],
              'solver_sha256':'c'*64,'source_file_count':2}
    freeze=save('freeze.json',{'schema':'orbit-poc-v4-validation-source-freeze-v1','source':{'sha256':'a'*64,'files':{
        'source.cpp':source['sha256'],'src/orbit_poc/segmented/tangent_export.py':decoder['sha256']}},'comparison_source':{'sha256':'b'*64}})
    controller=save('controller.json',{'schema':'orbit-poc-v4-cli-validation-controller-v1','status':'passed','returncode':0,
        'interrupted_or_timeout':False,'source':{'sha256':'a'*64}})
    build=save('build.json',{'schema':'orbit-poc-native-complete-build-v1','status':'built_complete_candidate',
        'native':native,'candidate_source_sha256':'d'*64})
    ba=save('build-audit.json',{'schema':'orbit-poc-native-complete-build-independent-review-v1','passed':True,
        'actual_build_result':build,'native':native,'candidate_source_sha256':'d'*64})
    bp=save('provenance.json',{'schema':'orbit-poc-v4-native-rebuild-provenance-v3','status':'verified_actual_complete_rebuild','actual_build_result':build})
    artifacts={'source_freeze':freeze,'controller':controller,'native_rebuild_provenance':bp}
    audit=save('audit.json',{'schema':'orbit-poc-segmented-validation-terminal-independent-review-v1',
        'consistency_passed':True,'scientific_status':'passed_scoped_checks','cleanup_verified':True,
        'identity':identity,'artifacts':artifacts,'supporting_reviews':[ba]})
    oldxml=fixture_xml().replace(b'/old/physical_initial.txt',str(initial['path']).encode()).replace(b'/old/attitude.txt',str(att['path']).encode())
    # The retained reference aliases an OLD output. It must not alias NEW output.
    oldxml=oldxml.replace(b'/old/orbit.txt',str(reference['path']).encode())
    xp=save('historical.xml',oldxml)
    historical=save('historical.json',{'schema':'flight-staged-refinement-3.1','status':'complete','passed':True,
        'binary_sha256':native['sha256'],'physical_initial_sha256':initial['sha256'],
        'physical_input_hashes':{att['path']:att['sha256']},'date':'2024-04-24','start_utc_seconds':42300,
        'duration_seconds':1800,'code_threshold_m':.003,'carrier_threshold_m':3e-5})
    attribution=save('attribution.json',{'schema':'orbit-poc-validation07-coarse-flight-invocation-attribution-v1',
        'status':'read_only_attribution_complete','independent_terminal_audit':audit,
        'native_invocation':{'native_binary_sha256':native['sha256'],'config_sha256':xp['sha256']},
        'archived_records':[{'source':historical}], 'retention_constraint':{'current_missing_confirmed':True,
        'missing_original_input':{'path':'/old/seed.dat','sha256':'e'*64,'status':'deleted'},
        'retained_final_reference_candidate':reference}})
    env={'ORBIT_POC_NUMERICS_QR_PREFIX':'<LEG>/native-prefix','HOME':'/test/home',
         **{k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')}}
    x={'schema':a.REQUEST_SCHEMA,'native':native,'build_result':build,'build_audit':ba,'decoder':decoder,
       'historical_result':historical,'historical_xml':xp,'fixed_initial':initial,'reference_orbit':reference,
       'input_pins':[att,initial,reference],'source_pins':[source,decoder],'validation_terminal_audit':audit,
       'audited_artifacts':artifacts,'expected_identity':identity,'historical_attribution':attribution,
       'environment':env,'output_dir':str(out)}
    p=tmp_path/'request.json';write(p,x);return x,p


def rewrite(x,p):write(p,x);return str(p),g.digest(p)


def repin(x,key,mutation):
    p=Path(x[key]['path']);value=json.loads(p.read_text());mutation(value);x[key]=write(p,value)


def test_actual_terminal_audit_schema_is_accepted_without_fabricated_passed():
    audit=json.loads((C/'validation07-terminal-independent-review01.json').read_text())
    assert 'passed' not in audit
    pins={k:{'path':v['path'],'sha256':v['sha256']} for k,v in audit['artifacts'].items() if k in a.ARTIFACT_KEYS}
    a.check_terminal_audit(audit,audit['identity'],pins)


@pytest.mark.parametrize('field,value',[('schema','other'),('consistency_passed',False),('consistency_passed',1),
    ('scientific_status','passed'),('cleanup_verified',False),('cleanup_verified','yes')])
def test_actual_schema_status_cleanup_fail_closed(field,value):
    audit=json.loads((C/'validation07-terminal-independent-review01.json').read_text());audit[field]=value
    pins={k:{'path':v['path'],'sha256':v['sha256']} for k,v in audit['artifacts'].items() if k in a.ARTIFACT_KEYS}
    with pytest.raises(ValueError):a.check_terminal_audit(audit,audit['identity'],pins)


def test_generic_passed_flag_does_not_replace_actual_schema():
    with pytest.raises(ValueError):a.check_terminal_audit({'passed':True},{},{})


@pytest.mark.parametrize('field',sorted(a.IDENTITY_KEYS))
def test_terminal_source_native_solver_count_identity_bound(field):
    audit=json.loads((C/'validation07-terminal-independent-review01.json').read_text());identity=deepcopy(audit['identity'])
    identity[field]=999 if field=='source_file_count' else '0'*64
    pins={k:{'path':v['path'],'sha256':v['sha256']} for k,v in audit['artifacts'].items() if k in a.ARTIFACT_KEYS}
    with pytest.raises(ValueError,match='identity'):a.check_terminal_audit(audit,identity,pins)


@pytest.mark.parametrize('field',sorted(a.ARTIFACT_KEYS))
def test_terminal_controller_freeze_build_provenance_pins_bound(field):
    audit=json.loads((C/'validation07-terminal-independent-review01.json').read_text())
    pins={k:{'path':v['path'],'sha256':v['sha256']} for k,v in audit['artifacts'].items() if k in a.ARTIFACT_KEYS};pins[field]['sha256']='0'*64
    with pytest.raises(ValueError,match='identity'):a.check_terminal_audit(audit,audit['identity'],pins)


def test_prepare_both_new_legs_without_execution_or_historical_replay_claim(tmp_path):
    x,p=make(tmp_path);plan=a.prepare(*rewrite(x,p))
    assert plan['status']=='prepared_not_executed' and not plan['scientific_pass']
    assert not plan['native_execution_performed'] and not plan['historical_refinement_rerun']
    assert [leg['name'] for leg in plan['legs']]==['no-export','export']
    for leg in plan['legs']:
        root=ET.parse(leg['config']['path']).getroot()
        assert root.findtext('.//PreprocessingVariationalEquation/inputfileOrbit')==x['reference_orbit']['path']
        assert x['reference_orbit']['path'] not in a.output_paths(root)
        assert leg['environment']['ORBIT_POC_NUMERICS_QR_PREFIX']==str(Path(x['output_dir'])/leg['name']/'native-prefix')
        assert root.findtext('.//OrbitPocEvaluateVariational/inputfileInitialState')==x['fixed_initial']['path']
        assert (root.find('.//orbitPocSegmentedTangentExport') is not None)==(leg['name']=='export')
    assert b'/old/seed.dat' in Path(x['historical_xml']['path']).read_bytes()
    with pytest.raises(ValueError,match='Fresh'):a.prepare(*rewrite(x,p))


@pytest.mark.parametrize('change',[
    lambda x:x.update(extra=True),lambda x:x['input_pins'].pop(),
    lambda x:x['environment'].pop('ORBIT_POC_NUMERICS_QR_PREFIX'),
    lambda x:x['environment'].update(ORBIT_POC_NUMERICS_QR_PREFIX='/unscoped'),
    lambda x:x['environment'].update(ORBIT_POC_OTHER='1'),lambda x:x['environment'].update(OMP_NUM_THREADS='2'),
    lambda x:x['environment'].pop('HOME'),lambda x:x['native'].update(sha256='0'*64),
    lambda x:x['expected_identity'].update(full_source_sha256='0'*64),
    lambda x:x['audited_artifacts'].pop('controller'),
])
def test_unsafe_request_fails_before_output_creation(tmp_path,change):
    x,p=make(tmp_path);change(x)
    with pytest.raises(ValueError):a.prepare(*rewrite(x,p))
    assert not Path(x['output_dir']).exists()


@pytest.mark.parametrize('key,change',[
    ('build_result',lambda v:v.update(status='failed')),
    ('build_audit',lambda v:v.update(passed=False)),
    ('historical_result',lambda v:v.update(binary_sha256='0'*64)),
    ('historical_result',lambda v:v.update(carrier_threshold_m=.004)),
    ('historical_attribution',lambda v:v['native_invocation'].update(config_sha256='0'*64)),
    ('historical_attribution',lambda v:v['retention_constraint'].update(current_missing_confirmed=False)),
    ('historical_attribution',lambda v:v['retention_constraint']['retained_final_reference_candidate'].update(sha256='0'*64)),
    ('historical_attribution',lambda v:v['retention_constraint']['missing_original_input'].update(path='/wrong/input')),
])
def test_changed_build_history_reference_identity_rejected(tmp_path,key,change):
    x,p=make(tmp_path);repin(x,key,change)
    with pytest.raises(ValueError):a.prepare(*rewrite(x,p))
    assert not Path(x['output_dir']).exists()


def test_output_overlap_rejected_before_write(tmp_path):
    x,p=make(tmp_path);x['output_dir']=str(tmp_path/'inputs'/'new')
    # Make a source parent itself protected to demonstrate ancestor refusal.
    x['output_dir']=str(Path(x['fixed_initial']['path'])/'new')
    with pytest.raises(ValueError):a.prepare(*rewrite(x,p))


def test_matching_config_keeps_retained_old_output_as_input_after_rename():
    configs=a.matched_configs(fixture_xml(),'/old/seed.dat','/old/orbit.txt','/fresh')
    for leg in configs.values():
        root=ET.fromstring(leg['xml'])
        assert root.findtext('.//PreprocessingVariationalEquation/inputfileOrbit')=='/old/orbit.txt'
        assert '/old/orbit.txt' not in a.output_paths(root)
        assert root.findtext('.//FileConvert/inputfile')==leg['outputs']['orbit_binary']


def test_no_export_leg_does_not_accidentally_add_stm_export():
    configs=a.matched_configs(fixture_xml(),'/old/seed.dat','/retained/orbit.dat','/fresh')
    no=ET.fromstring(configs['no-export']['xml']);yes=ET.fromstring(configs['export']['xml'])
    assert no.find('.//OrbitPocStateDerivatives') is None and yes.find('.//OrbitPocStateDerivatives') is not None


@pytest.mark.parametrize('change',[lambda v:v.update(profile='legacy_v3'),lambda v:v.update(omitted_terms=[]),
    lambda v:v.update(maximum_tangent_relative_residual=2.0001e-12),lambda v:v.update(maximum_tangent_relative_residual=float('nan'))])
def test_no_export_native_guard_is_required(change):
    value={'profile':'flight_gravity_drag_v1','omitted_terms':a.OMITTED[:],'maximum_tangent_relative_residual':1e-13};change(value)
    with pytest.raises(ValueError):a.check_derivatives(value)


def execution_fixture(tmp_path):
    x,p=make(tmp_path);plan=a.prepare(*rewrite(x,p));leg=plan['legs'][0]
    receipt={'schema':'orbit-poc-matched-flight-leg-execution-v1','returncode':0,'timed_out':False,'interrupted':False,
        'config_sha256':leg['config']['sha256'],'native_sha256':x['native']['sha256'],'environment':leg['environment'],
        'argv':leg['argv'],'cwd':leg['cwd'],'input_pins':x['input_pins']}
    return x,leg,receipt


def test_complete_explicit_new_execution_receipt_is_accepted(tmp_path):
    a.check_execution_receipt(*execution_fixture(tmp_path))


@pytest.mark.parametrize('field,value',[
    ('schema','run_native'),('returncode',1),('timed_out',True),('interrupted',True),
    ('config_sha256','0'*64),('native_sha256','0'*64),('environment',{}),('argv',[]),('cwd','/wrong'),('input_pins',[]),
])
def test_wrong_failed_or_interrupted_execution_cannot_credit_pair(tmp_path,field,value):
    x,leg,receipt=execution_fixture(tmp_path);receipt[field]=value
    with pytest.raises(ValueError):a.check_execution_receipt(x,leg,receipt)


def test_coherently_changed_receipt_and_plan_cannot_replace_native_invocation(tmp_path):
    x,leg,receipt=execution_fixture(tmp_path);leg['argv'][0]='/wrong-native'
    with pytest.raises(ValueError,match='Planned native'):a.check_execution_receipt(x,leg,receipt)
