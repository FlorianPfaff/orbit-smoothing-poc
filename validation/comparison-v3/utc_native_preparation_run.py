from pathlib import Path
import json,sys,os,shutil,subprocess,xml.etree.ElementTree as ET
sys.path.insert(0,str(Path('outputs/orbit-smoothing-poc/src').resolve()))
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
from orbit_poc.comparison.groops_config import build_day_configs,run_native_preparation
from orbit_poc.comparison.data import sha256_file,write_json
root=Path('/tmp/orbit-v3-utc-final');root.mkdir(exist_ok=True)
binary=root/'groops';shutil.copy2('/tmp/orbit-v3-runtime/groops-build/groops',binary)
manifest=json.loads(Path('work/v3/prepared-utc/2024-04-24/data_manifest.json').read_text())
for label,intervals in [('normal',[]),('blackout',[[39600,46800]])]:
    out=root/label
    result=build_day_configs(manifest,'work/v3/native-example/scenarioLeoReducedDynamicOrbit','work/v3/groops-data',out,
        mask={'intervals_seconds':intervals,'cadence_seconds':30,'time_scale':'UTC'})
    print('configured',label,result['preprocessing']['bootstrap']['solved_epochs'],flush=True)
    result=run_native_preparation(result,binary)
    convert=ET.Element('groops')
    for name in ['orbit','attitude','receiver']:
        p=ET.SubElement(ET.SubElement(convert,'program'),'FileConvert')
        ET.SubElement(p,'inputfile').text=result['native_paths'][name]
        ET.SubElement(p,'outputfile').text=str(out/f'{name}_ascii.txt')
    config=out/'check_ascii.xml';ET.ElementTree(convert).write(config,encoding='utf-8',xml_declaration=True)
    with (out/'check_ascii.log').open('w') as stream:subprocess.run([str(binary),str(config)],stdout=stream,stderr=subprocess.STDOUT,check=True)
    print('prepared',label,sha256_file(binary),flush=True)
print('completed',flush=True)
