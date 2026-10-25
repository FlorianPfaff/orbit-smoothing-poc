"""One bounded diagnostic build/replay of the unchanged native reference fit."""
from pathlib import Path
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PARENT = Path('/mnt/d/orbit-v41-recovery01/candidate04')
NATIVE = PARENT / 'native-source-04/source'
BUILD = PARENT / 'build-04'
PREFIX = Path('/home/emper/orbit-nuisance-warmstarts/toolchain-01')
PYTHON = '/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python'
ORBIT = Path('/mnt/d/orbit-v41-recovery02/one-hour-run01/cold-density/fit/point-004-trial-001/closure-01/orbit.dat')
OUT = ROOT / 'evidence/native-reference-probe01'
SCRATCH = Path('/home/emper/orbit-density-reference-probe06')


def pin(path):
    path = Path(path)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), mod.__dict__)
    return mod


def worker():
    plan = json.loads((OUT / 'plan.json').read_text())
    for entry in plan['pins']:
        if pin(entry['path']) != entry:
            raise RuntimeError('Diagnostic dependency changed: ' + entry['path'])
    compiled = subprocess.run(plan['compiler_argv'], check=False)
    if compiled.returncode:
        return compiled.returncode
    save(OUT / 'diagnostic-binary.json', pin(SCRATCH / 'reference-probe'))
    with (OUT / 'trace.jsonl').open('x') as stream:
        replay = subprocess.run([str(SCRATCH / 'reference-probe'), str(OUT / 'orbit.dat')],
                                stdout=stream, stderr=subprocess.STDOUT, check=False)
    save(OUT / 'replay-result.json', {'returncode': replay.returncode, 'trace': pin(OUT / 'trace.jsonl'),
         'scope': 'Exact native mean-reference construction on archived binary states; no force propagation or fit'})
    return replay.returncode


def main():
    if '--worker' in sys.argv:
        return worker()
    if OUT.exists() or SCRATCH.exists():
        raise RuntimeError('Preserve prior diagnostic output')
    OUT.mkdir(); SCRATCH.mkdir(mode=0o700)
    text = (NATIVE / 'programs/preprocessing/preprocessingVariationalEquation.cpp').read_text()
    begin = text.index('      UInt stagger = (orbit.size() < 100)')
    end = text.index('\n      if(iter == maxIter)', begin)
    original = text[begin:end]
    instrumented = original.replace('      UInt   iter    = 0;', '      report(0, referenceOrbit);\n      UInt   iter    = 0;')
    instrumented = instrumented.replace('        referenceOrbit.l0 += dx(5);',
                                       '        referenceOrbit.l0 += dx(5);\n        report(iter+1, referenceOrbit);')
    probe = '''#include "base/import.h"
#include "base/equinoctial.h"
#include "files/fileInstrument.h"
#include "misc/orbitPoc/preciseEquinoctialReference.h"
void report(unsigned iteration, const Equinoctial &e) {
  std::cout << std::setprecision(20) << "{\\\"iteration\\\":" << iteration;
  const char *names[]={"GM","a","h","k","p","q","l0"};
  const long double values[]={e.GM,e.a,e.h,e.k,e.p,e.q,e.l0};
  for(unsigned i=0;i<7;i++) {
    std::cout << ",\\\"" << names[i] << "\\\":";
    if(std::isfinite(values[i])) std::cout << values[i]; else std::cout << "null";
  }
  std::cout << "}\\n" << std::flush;
}
int main(int argc, char **argv) {
  try {
    if(argc!=2)return 4;
    InstrumentFile input{FileName(argv[1])};
    const OrbitArc orbit=input.readArc(0);
    const Double GM=3.986004415e14;
''' + instrumented + '''
    try {
      auto result=OrbitPoc::preciseEquinoctialReference(
        {referenceOrbit.GM,referenceOrbit.a,referenceOrbit.h,referenceOrbit.k,referenceOrbit.p,referenceOrbit.q,referenceOrbit.l0},0.L);
      std::cout << "{\\\"guard\\\":\\\"unexpected_success\\\"}\\n"; return 3;
    } catch(const std::exception &e) {
      std::cout << "{\\\"guard_error\\\":\\\"" << e.what() << "\\\"}\\n";
      return std::string(e.what())=="Nonfinite equinoctial reference input" ? 0 : 5;
    }
  } catch(const std::exception &e) {std::cerr << e.what() << std::endl;return 2;}
}
'''
    (OUT / 'original-reference-loop.cpp.txt').write_text(original)
    (OUT / 'probe.cpp').write_text(probe)
    shutil.copyfile(ORBIT, OUT / 'orbit.dat')
    objects = [p for p in sorted((BUILD / 'CMakeFiles/groopscore.dir').rglob('*.o')) if p.name != 'groops.cpp.o']
    objects.append(BUILD / 'CMakeFiles/groops.dir/parallel/parallelSingle.cpp.o')
    compiler = PREFIX / 'bin/x86_64-conda-linux-gnu-c++'
    libraries = [PREFIX / ('lib/lib' + n + '.so') for n in ['blas','lapack','expat','erfa','z']]
    argv = [str(compiler), '-O3', '-DNDEBUG', '-std=gnu++17', '-DGROOPS_DISABLE_NETCDF',
            '-I'+str(NATIVE), '-I'+str(PREFIX/'include'), str(OUT/'probe.cpp'), *map(str, objects),
            '-Wl,-rpath,'+str(PREFIX/'lib'), *map(str, libraries), '-lstdc++fs','-lgfortran','-lquadmath',
            '-o', str(SCRATCH/'reference-probe')]
    recovery = load('/mnt/d/orbit-v41-recovery02/validation-controls07/reference_recovery.py', 'recovery')
    lock = os.open('/mnt/d/orbit-v41-recovery02/validation-controls07/cooperative-admission.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        if os.fstat(lock).st_uid != os.getuid():raise RuntimeError('Foreign admission lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        admission = recovery.admission(cpu=4)
        if shutil.disk_usage(SCRATCH).free < 32*1024**3:raise RuntimeError('Insufficient scratch')
        dependencies = [*objects, *libraries, compiler, Path(__file__), OUT/'probe.cpp', ORBIT, OUT/'orbit.dat',
                        NATIVE/'programs/preprocessing/preprocessingVariationalEquation.cpp',
                        *sorted(NATIVE.rglob('*.h'))]
        save(OUT/'plan.json', {'schema':'native-reference-probe-plan-v1', 'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'admission':admission,'compiler_argv':argv,'pins':[pin(p) for p in dependencies],
             'limits':{'wall_seconds':180,'rss_bytes':2*1024**3,'cpu':4,'threads':1},
             'reference_loop_changes':'Element logging only; unchanged construction, sparse sampling, analytic state transitions and native leastSquares',
             'production_source_modified':False,'full_fit':False})
        sys.path.insert(0,str(PARENT/'source/src'))
        from orbit_poc.segmented.supervisor import run_owned
        environment = {'PATH':str(PREFIX/'bin')+':/usr/bin:/bin','HOME':os.environ['HOME'],
            'LD_LIBRARY_PATH':str(PREFIX/'lib'),'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
            'NUMEXPR_NUM_THREADS':'1','BLIS_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1', 'TMPDIR':str(SCRATCH),
            'PYTHONPATH':str(PARENT/'source/src')}
        result=run_owned(['/usr/bin/taskset','-c','4',PYTHON,'-s','-B',str(Path(__file__).resolve()),'--worker'],
            python_executable=PYTHON,cwd=OUT,env=environment,log_path=OUT/'worker.log',receipt_path=OUT/'supervisor.json',
            timeout_seconds=180,max_process_tree_rss_bytes=2*1024**3,min_free_disk_bytes=32*1024**3,working_directory=SCRATCH)
        print(json.dumps({'status':result['status'],'output':str(OUT)}))
        return 0 if result['status']=='complete' else 1
    finally:
        os.close(lock)


if __name__ == '__main__':
    sys.exit(main())
