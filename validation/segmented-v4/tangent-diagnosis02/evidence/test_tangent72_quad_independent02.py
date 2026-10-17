from pathlib import Path
import decimal,importlib.util,subprocess,tempfile,struct,json,hashlib,shutil
C=Path('/mnt/d/orbit-segmented-v4/control');src=C/'tangent72-diagnostic03';dst=C/'tangent72-diagnostic03-independent01';dst.mkdir()
for n in ['replay.cpp','probe.cpp']:shutil.copy2(src/n,dst/n)
include=C/'tangent72-diagnostic01/include'
for n in ['replay','probe']:
 subprocess.run(['g++','-O3','-DNDEBUG','-std=gnu++17','-I'+str(include),str(dst/(n+'.cpp')),'-o',str(dst/n)],check=True,capture_output=True)
spec=importlib.util.spec_from_file_location('base',C/'tangent72-diagnostic01/test_replay.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);base.HERE=dst
results=[]
for name in sorted(n for n in dir(base)if n.startswith('test_')):
 sub=dst/name;sub.mkdir();getattr(base,name)(sub);results.append(name)
# Independent decimal residual on nonzero position/velocity Jacobians and quadrature.
b=bytearray(base.capture());jac=[]
for epoch in range(3):
 vals=[0.]*18
 for axis in range(3):
  vals[4*axis]=-.001*(axis+1)*(epoch+1);vals[9+4*axis]=-.0001*(axis+1)
  if axis<2:vals[3*axis+axis+1]=.0003
 jac.append(vals)
 struct.pack_into('<18d',b,72+8*18*epoch,*vals)
path=dst/'decimal-nonzero.bin';path.write_bytes(b)
run=subprocess.run([str(dst/'probe'),str(path)],capture_output=True,text=True,check=True);rows=run.stdout.splitlines();q=json.loads(rows[3]);assert q['binary_digits']==113
D=decimal.Decimal
with decimal.localcontext()as ctx:
 ctx.prec=90
 rhs=list(struct.unpack_from('<18d',b,len(b)-144));x=rhs[:9]+[v*1000. for v in rhs[9:]];x[0]+=.25
 def expected(native):
  acc=[]
  for k in range(3):
   for i in range(3):
    v=D(0)
    for j in range(3):
     velocity=D.from_float(x[9+3*k+j]*(1./1000.))if native else D.from_float(x[9+3*k+j])/1000
     v+=D.from_float(jac[k][3*i+j])*D.from_float(x[3*k+j])+D.from_float(jac[k][9+3*i+j])*velocity
    acc.append(v)
  p=[D(0)]*3;vel=[D(0)]*3;ss=D(0);nn=D(0)
  for k in range(3):
   if k:
    for i in range(3):
     integ=D.from_float(.25)*(acc[3*(k-1)+i]+acc[3*k+i]);moment=D.from_float(1./24.)*acc[3*(k-1)+i]+D.from_float(1./12.)*acc[3*k+i]
     p[i]+=D.from_float(.5)*(vel[i]+integ)-moment;vel[i]+=integ
   for i in range(3):
    bp=D.from_float(rhs[3*k+i]);bv=D.from_float(rhs[9+3*k+i]*1000.)
    rp=bp-D.from_float(x[3*k+i])+p[i];rv=bv-D.from_float(x[9+3*k+i])+1000*vel[i]
    ss+=rp*rp+rv*rv;nn+=bp*bp+bv*bv
  return (ss/nn).sqrt()
 want=expected(True);assert abs(D(rows[2])-want)<(D(2)**-62)*max(D(1),abs(want)),(rows[2],want)
 # JSON conversion loses precision, so compare its binary64-rounded scalar.
 for mode in [True,False]:
  key='relative_residual_'+('native'if mode else'exact')+'_velocity_conversion'
  assert abs(q[key]-float(expected(mode)))<1e-18
results.append('nonzero_quad_residual_vs_independent_90_digit_decimal')
out=dict(schema='orbit-poc-tangent-quad-independent-fixtures-v1',passed=True,tests=results,passed_count=len(results),failed_count=0,skipped_count=0,source_sha256=hashlib.sha256((src/'replay.cpp').read_bytes()).hexdigest(),compiler=subprocess.run(['g++','--version'],capture_output=True,text=True,check=True).stdout,scope='Small synthetic fixture binaries only. No original 72-hour capture or native propagation executed.',quad_native_decimal=str(want),quad_native_observed=rows[2])
(dst/'result.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
