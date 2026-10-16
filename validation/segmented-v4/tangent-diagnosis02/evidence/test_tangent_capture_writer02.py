from pathlib import Path
import subprocess,os,struct,json,hashlib,resource,signal
import pytest
C=Path(__file__).parent
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
 d=tmp_path_factory.mktemp('writer');p=d/'fixture.cpp';block=(C/'tangent_capture_block01.txt').read_text()
 p.write_text('''#include <array>\n#include <vector>\n#include <string>\n#include <limits>\n#include <cstdio>\n#include <cstdlib>\n#include <stdexcept>\n#include <csignal>\nusing Bool=bool;using Exception=std::runtime_error;\nstruct J{std::array<double,9> position{},velocity{};};\nstruct Q{unsigned index;double integral,moment;};\nint main(int argc,char **argv){\n std::signal(SIGXFSZ,SIG_IGN);\n bool synthetic=argc<2 || std::string(argv[1])!="flight";const char *role="physical_correction";unsigned c=0,epochCount=2;double deltaT=5,T=5;\n std::vector<J> mainJac(2),preconditionJac(2);\n for(int k=0;k<2;k++)for(int i=0;i<9;i++){mainJac[k].position[i]=100*k+i+.25;mainJac[k].velocity[i]=-100*k-i-.5;preconditionJac[k].position[i]=100*k+i+.75;preconditionJac[k].velocity[i]=-100*k-i-.875;}\n std::vector<std::vector<Q>> mainWeights{{{0,2.5,4.125},{1,2.5,8.375}}};\n std::vector<double> rhs{1,2,3,4,5,6,7,8,9,10,11,12};\n try {\n'''+block+'''\n } catch(const std::exception &error){std::fprintf(stderr,"%s\\n",error.what());return 2;}\n return 0;}\n''')
 subprocess.run(['/usr/bin/g++','-std=c++17','-O2','-Wall','-Wextra','-Werror',str(p),'-o',str(d/'writer')],check=True,capture_output=True)
 return d/'writer'
def run(binary,path=None,args=(),preexec_fn=None):
 env={k:v for k,v in os.environ.items() if k!='ORBIT_POC_TANGENT_CAPTURE'}
 if path is not None:env['ORBIT_POC_TANGENT_CAPTURE']=str(path)
 return subprocess.run([str(binary),*args],env=env,capture_output=True,preexec_fn=preexec_fn)
def test_exact_scalar_roundtrip(binary,tmp_path):
 p=tmp_path/'capture';r=run(binary,p);assert r.returncode==0,r.stderr;raw=p.read_bytes();assert raw[:16]==b'OPCTANGENT001\n\0\0';assert struct.unpack_from('<5Q2d',raw,16)==(1,2,1,2,12,5.,5.)
 a=struct.unpack_from('<72d',raw,72);assert a[:9]==tuple(i+.25 for i in range(9));assert a[9:18]==tuple(-i-.5 for i in range(9));assert a[36:45]==tuple(i+.75 for i in range(9));at=72+72*8
 assert struct.unpack_from('<Q',raw,at)==(2,);at+=8
 assert struct.unpack_from('<QddQdd',raw,at)==(0,2.5,4.125,1,2.5,8.375);at+=48
 assert struct.unpack_from('<12d',raw,at)==tuple(float(i)for i in range(1,13));assert len(raw)==at+96
def test_refuse_overwrite(binary,tmp_path):
 p=tmp_path/'capture';p.write_bytes(b'preserved');r=run(binary,p);assert r.returncode==2 and p.read_bytes()==b'preserved'
def test_no_env_no_capture(binary,tmp_path):assert run(binary).returncode==0
def test_other_profile_no_capture(binary,tmp_path):
 p=tmp_path/'capture';assert run(binary,p,('flight',)).returncode==0;assert not p.exists()
def test_partial_write_is_failure(binary,tmp_path):
 p=tmp_path/'capture'
 def limit():resource.setrlimit(resource.RLIMIT_FSIZE,(16,16))
 r=run(binary,p,preexec_fn=limit);assert r.returncode==2 and b'close failed' in r.stderr and p.stat().st_size==16
def test_capture_block_only_source_delta():
 old=Path('/mnt/d/orbit-segmented-v4/validation-04-packet/source/groops/extension/stagedVariationalBody.h').read_text();new=(C/'stagedVariationalBody-tangent-capture01.h').read_text();block=(C/'tangent_capture_block01.txt').read_text();assert new.replace(block,'')==old
