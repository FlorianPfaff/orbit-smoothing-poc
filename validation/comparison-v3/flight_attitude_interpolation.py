from pathlib import Path
import sys,subprocess,xml.etree.ElementTree as ET,json,numpy as np
sys.path.insert(0,str(Path('outputs/orbit-smoothing-poc/src').resolve()))
from orbit_poc.comparison.data import _gps1b_text,write_json,sha256_file
folder=Path('/tmp/orbit-v3-attitude-alias').resolve();folder.mkdir(exist_ok=True)
base=Path('work/v3/flight-refinement-local-events/groops_pulses').resolve()
tree=ET.Element('groops')
for label in ['coarse','fine']:
 p=ET.SubElement(ET.SubElement(tree,'program'),'InstrumentResample')
 for tag,value in [('inputfileInstrument',str(base/label/'attitude.dat')),('outputfileInstrument',str(folder/f'{label}_1s.txt'))]:ET.SubElement(p,tag).text=value
 method=ET.SubElement(ET.SubElement(p,'method'),'polynomial')
 for tag,value in [('polynomialDegree','7'),('maxDataPointRange','-8.1'),('maxExtrapolationDistance','-1.1')]:ET.SubElement(method,tag).text=value
 grid=ET.SubElement(ET.SubElement(p,'timeSeries'),'uniformSampling')
 for tag,value in [('timeStart','60424'),('timeEnd','60424+86390.1/86400'),('sampling','1/86400')]:ET.SubElement(grid,tag).text=value
config=folder/'resample.xml';ET.ElementTree(tree).write(config,encoding='utf-8',xml_declaration=True)
with (folder/'resample.log').open('w') as log:subprocess.run(['/tmp/orbit-v3-common-preprocessing/groops',str(config)],stdout=log,stderr=subprocess.STDOUT,check=True)
def table(path):
 rows=[line.split() for line in path.read_text().splitlines() if len(line.split())==5 and line.split()[0].startswith('60424.')]
 return np.array([[float(x) for x in r[1:]] for r in rows])
def diff(q,p):
 q=q/np.linalg.norm(q,axis=1)[:,None];p=p/np.linalg.norm(p,axis=1)[:,None]
 p=p*np.where(np.sum(q*p,axis=1)<0,-1,1)[:,None]
 return 4*np.arcsin(np.clip(np.linalg.norm(p-q,axis=1)/2,0,1))
source=Path('work/v3/prepared-utc/2024-04-24/raw_gps_days/2024-04-24/estimation/SCA1B_2024-04-24_C_04.txt')
raw=np.array([[float(x) for x in row.split()[3:7]] for row in _gps1b_text(source)[1]])
a,b=table(folder/'coarse_1s.txt'),table(folder/'fine_1s.txt');raw=raw[:len(a)]
records={}
for name,angles in [('raw1s_vs_5s_interpolated',diff(raw,a)),('raw1s_vs_2_5s_interpolated',diff(raw,b)),('5s_curve_vs_reinterpolated2_5s_curve',diff(a,b))]:
 records[name]={'maximum_rad':float(max(angles)),'rms_rad':float(np.sqrt(np.mean(angles**2))),'median_rad':float(np.median(angles)),'p99_rad':float(np.quantile(angles,.99)),'maximum_time_gps_seconds':int(np.argmax(angles))}
write_json(folder/'attitude_alias.json',{'scope':'Read-only numerical attitude diagnostic; no fitting or force model change','epochs':len(a),'raw_sca_sha256':sha256_file(source),'comparisons':records,'fine_input':'Current refinement2.5s attitude is already degree7 interpolation of original5s saved attitude, not raw1s samples','force_effect_not_measured':True})
print(json.dumps(records,indent=2))
