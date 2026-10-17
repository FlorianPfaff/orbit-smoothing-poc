"""D03 fabricated controls/shape tests; no native estimator or server work."""
import copy,hashlib,importlib.util,json,os,shutil,subprocess
from pathlib import Path
import pytest
HERE=Path(__file__).parent

def load(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
I=load('install_nuisance_trace');V=load('verify_trace_equivalence')

def synthetic_source(tmp_path):
    # Collect the installer's exact anchors into deliberately minimal fake files.
    # Actual installed-source compatibility is separately checked read-only.
    anchors={};current=[None];real=I.once
    class Fake:
        def __truediv__(self,name):current[0]=name;return self
        def read_text(self):anchors[current[0]]=[];return ''
    def collect(text,old,new):
        if old not in text:anchors[current[0]].append(old);text+='\n'+old+'\n'
        return real(text,old,new)
    I.once=collect
    try:I.patched_files(Fake())
    finally:I.once=real
    source=tmp_path/'tree'/'source'
    for name,parts in anchors.items():p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(parts)+'\n')
    return source

def test_all_anchors_validate_before_writing(tmp_path):
    source=synthetic_source(tmp_path);before={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    p=source/'gnss/gnssParametrization/gnssParametrizationClocks.cpp';p.write_text('missing final anchor')
    expected={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):I.install(source.parent,tmp_path/'receipt.json')
    assert {str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}==expected
    assert len(before)==15 and not (tmp_path/'receipt.json').exists()

def test_installer_receipt_and_reapplication_refusal(tmp_path):
    source=synthetic_source(tmp_path);result=I.install(source.parent,tmp_path/'receipt.json')
    assert len(result['files'])==16 and result['diagnostic_only'] is True
    for name,item in result['files'].items():assert hashlib.sha256((source/name).read_bytes()).hexdigest()==item['after']
    with pytest.raises(ValueError):I.install(source.parent,tmp_path/'other.json')

@pytest.mark.parametrize('name,needle',[
 ('gnss/gnssDesignMatrix.cpp','joint_global_design'),('gnss/gnssProcessingStep/gnssProcessingStep.cpp','joint_local_requested'),
 ('misc/orbitPoc/scaledRowQr.h','constraint_original_coefficient'),('gnss/gnssObservation.cpp','complete_original_precise'),
 ('misc/orbitPoc/gnssRangeResidual.h','distance_before_narrowing'),('gnss/gnssTransmitter.h','transmitter_velocity_interpolation'),
 ('base/polynomial.cpp','polynomial_node_value_'),('gnss/gnssReceiver.h','receiver_antenna_offset'),
 ('gnss/gnssParametrization/gnssParametrizationClocks.cpp','clock_requested_seconds'),
 ('gnss/gnssParametrization/gnssParametrizationIonosphereVTEC.cpp','VTEC_STEC_after'),
 ('gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp','ambiguity_type_mapping'),
 ('gnss/gnssTransceiver.h','shared_signal_bias_native'),('gnss/gnssParametrization/gnssParametrizationIonosphereSTEC.cpp','sigmaSTEC')])
def test_required_capture_sites(tmp_path,name,needle):
    source=synthetic_source(tmp_path);updates=I.patched_files(source);assert needle in updates[name]

def sentinel():return {'schema':'orbit-poc-d03-generation-stop-v1','diagnostic_only':True,'scientific_complete':False,'completed_generations':4,'reason':'bounded diagnostic stopped before generation5'}
def replay(directory,count):
    directory.mkdir()
    for gen in range(1,count+1):
        for suffix in V.EXACT_SUFFIXES:(directory/f'qr.{gen}.{suffix}').write_bytes(b'fixture numerics '+str(gen).encode()+suffix.encode())
        (directory/f'qr.{gen}.rows.tsv').write_bytes(b'original rows')
        (directory/f'qr.{gen}.factor.json').write_text(json.dumps({'spool_directory':str(directory),'keep_intermediate_factors':False,'same':gen}))
        (directory/f'qr.{gen}.nuisance_line_search.json').write_text(json.dumps({'same':gen,'trials':[{'child_user_seconds':.2}]}))
    if count==4:(directory/'qr.diagnostic-incomplete.json').write_text(json.dumps(sentinel()))

def replays(tmp_path):
    dirs=[tmp_path/n for n in ('reference','off','on')]
    for p,n in zip(dirs,(6,4,4)):replay(p,n)
    return dirs

def test_reference_superset_and_diagnostic_exact_four(tmp_path):
    ds=replays(tmp_path);r=V.verify(ds,4);assert r['passed'] and len(r['checks'])==52 and not r['scientific_validation_complete']

def test_original_generation_four_can_be_retired_with_exact_receipt(tmp_path):
    ds=replays(tmp_path);items=[]
    for suffix,role in V.RETIREABLE.items():
        p=ds[0]/f'qr.4.{suffix}';items.append(dict(V.artifact(p),role=role));p.unlink()
    (ds[0]/'qr.4.retention.json').write_text(json.dumps({'schema':'orbit-poc-native-factor-retention-v1','status':'completed','artifacts':items}))
    assert V.verify(ds,4)['passed']

@pytest.mark.parametrize('case',['missing_reference','missing_diag','extra_diag','bad_sentinel','promoted_sentinel','changed_factor','changed_rows','changed_numeric_json','missing_retention','retired_final_diag'])
def test_incomplete_or_changed_equivalence_rejected(tmp_path,case):
    ds=replays(tmp_path)
    if case=='missing_reference':(ds[0]/'qr.2.factor.json').unlink()
    elif case=='missing_diag':(ds[1]/'qr.3.factor.json').unlink()
    elif case=='extra_diag':(ds[1]/'qr.5.factor.json').write_text('{}')
    elif case=='bad_sentinel':(ds[1]/'qr.diagnostic-incomplete.json').unlink()
    elif case=='promoted_sentinel':
        s=sentinel();s['scientific_complete']=True;(ds[1]/'qr.diagnostic-incomplete.json').write_text(json.dumps(s))
    elif case=='changed_factor':(ds[1]/'qr.4.R.bin').write_bytes(b'changed')
    elif case=='changed_rows':(ds[1]/'qr.4.rows.tsv').write_bytes(b'changed')
    elif case=='changed_numeric_json':(ds[1]/'qr.4.nuisance_line_search.json').write_text('{}')
    elif case=='missing_retention':(ds[0]/'qr.4.R.bin').unlink()
    else:(ds[1]/'qr.4.R.bin').unlink()
    with pytest.raises((ValueError,FileNotFoundError)):V.verify(ds,4)

def test_only_explicit_timing_differences_ignored(tmp_path):
    ds=replays(tmp_path);p=ds[1]/'qr.4.nuisance_line_search.json';v=json.loads(p.read_text());v['trials'][0]['child_user_seconds']=9;p.write_text(json.dumps(v));assert V.verify(ds,4)['passed']

def test_header_has_real_hidden_vector_interface_and_generation_contract(tmp_path):
    compiler=shutil.which('g++')
    if not compiler:pytest.fail('Standalone header API fixture requires local g++')
    src=tmp_path/'shape.cpp';src.write_text(r'''
#include "nuisanceArithmeticTrace.h"
#include <vector>
struct Matrix {unsigned rows()const{return 2;}unsigned columns()const{return 1;}double operator()(unsigned,unsigned)const{return 1.;}};
struct Vector:Matrix {double operator()(unsigned)const{return 2.;}};
struct Pair {long double high,low;};
struct Vec3 {double x()const{return 1.;}double y()const{return 2.;}double z()const{return 3.;}};
struct Time {int mjdInt()const{return 60000;}double mjdMod()const{return .25;}};
int main(int argc,char **argv){
 if(argc>1){setenv("ORBIT_POC_D03_MAX_GENERATIONS","4",1);try{orbitPocD03::guard(4,argv[1]);}catch(const std::runtime_error&){return 7;}return 8;}
 Matrix m;Vector v;Pair p{1.L,1e-20L};std::vector<Pair> pairs{p};std::vector<unsigned> ids{2};std::vector<double> values{3.};
 orbitPocD03::generation("fixture/qr.4",4);orbitPocD03::Equation eq(0,1,2);orbitPocD03::matrix("matrix",m);orbitPocD03::matrix("hidden_vector",v);orbitPocD03::precise("precise",pairs);orbitPocD03::pairOperand("pair",p);orbitPocD03::vector3("vec3",Vec3());orbitPocD03::time("time",Time());orbitPocD03::sparse("sparse",0,ids,values);orbitPocD03::guard(3,"unused");return 0;}
''')
    binary=tmp_path/'shape';subprocess.run([compiler,'-std=c++17','-O0','-frounding-math','-I',str(HERE),str(src),'-o',str(binary)],check=True,capture_output=True)
    subprocess.run([str(binary)],check=True,capture_output=True)
    prefix=tmp_path/'qr';r=subprocess.run([str(binary),str(prefix)],capture_output=True);assert r.returncode==7
    assert json.loads(prefix.with_suffix('.diagnostic-incomplete.json').read_text())==sentinel()

def test_phase_context_floating_environment_and_fork_files(tmp_path):
    compiler=shutil.which('g++')
    if not compiler:pytest.fail('Standalone context fixture requires local g++')
    src=tmp_path/'context.cpp';src.write_text(r'''
#include "nuisanceArithmeticTrace.h"
#include <sys/wait.h>
int main(int argc,char **argv){
 if(argc!=2)return 1;setenv("ORBIT_POC_D03_DIRECTORY",argv[1],1);
 orbitPocD03::generation("fixture/qr.3",3);orbitPocD03::scalar("wrong_generation",1.);
 orbitPocD03::generation("fixture/qr.4",4);
 {
  orbitPocD03::Equation outer(0,7,11);orbitPocD03::component("original_capture");
  errno=42;std::feclearexcept(FE_ALL_EXCEPT);std::feraiseexcept(FE_DIVBYZERO);const int before=std::fetestexcept(FE_ALL_EXCEPT);
  orbitPocD03::scalar("baseline_original",3.);
  if(errno!=42||std::fetestexcept(FE_ALL_EXCEPT)!=before)return 2;
  {orbitPocD03::Equation inner(1,8,12);orbitPocD03::scalar("nested_equation",4.);}
  if(orbitPocD03::context().receiver!=0||orbitPocD03::context().component!="original_capture")return 3;
 }
 if(orbitPocD03::context().receiver!=~0ULL)return 4;
 orbitPocD03::phase("joint");orbitPocD03::scalar("recovery_only",5.);
 orbitPocD03::trial(.5);orbitPocD03::scalar("unselected_fraction",6.);
 orbitPocD03::trial(1.);orbitPocD03::scalar("fullstep_before_fork",7.);
 const pid_t pid=fork();if(pid<0)return 5;if(pid==0){orbitPocD03::trial(0.);orbitPocD03::scalar("child_zero_replay",8.);_exit(0);}
 int status=0;if(waitpid(pid,&status,0)!=pid||!WIFEXITED(status)||WEXITSTATUS(status))return 6;
 if(orbitPocD03::context().phase!="trial"||orbitPocD03::context().alpha!=1.)return 7;
 orbitPocD03::scalar("parent_fullstep_after_fork",9.);return 0;
}
''')
    binary=tmp_path/'context';subprocess.run([compiler,'-std=c++17','-O0','-frounding-math','-I',str(HERE),str(src),'-o',str(binary)],check=True,capture_output=True)
    traces=tmp_path/'trace';traces.mkdir();subprocess.run([str(binary),str(traces)],check=True,capture_output=True)
    files=list(traces.glob('nuisance-trace-*.tsv'));assert len(files)==2
    rows=[line.split('\t') for p in files for line in p.read_text().splitlines()];assert all(len(r)==16 for r in rows)
    bystage={r[8]:r for r in rows};assert set(bystage)=={'baseline_original','nested_equation','recovery_only','fullstep_before_fork','child_zero_replay','parent_fullstep_after_fork'}
    assert bystage['baseline_original'][1]=='baseline' and bystage['baseline_original'][3:6]==['0','7','11']
    assert bystage['nested_equation'][3:6]==['1','8','12']
    assert bystage['recovery_only'][1]=='joint'
    assert float.fromhex(bystage['child_zero_replay'][2])==0
    assert float.fromhex(bystage['parent_fullstep_after_fork'][2])==1
