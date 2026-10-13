from pathlib import Path
import json,sys,subprocess,shutil,xml.etree.ElementTree as ET
sys.path.insert(0,str(Path('outputs/orbit-smoothing-poc/src').resolve()))
from orbit_poc.comparison.data import read_gps_osb,sha256_file,write_json
root=Path('work/v3/utc-native-osb').resolve();root.mkdir(exist_ok=True)
binary=root/'groops';shutil.copy2('/tmp/orbit-v3-runtime/groops-build/groops',binary)
records=[]
for day,doy in [('2024-04-24',115),('2024-04-25',116)]:
    source=Path(f'work/v3/data-cache/gnss/COD0OPSFIN_2024{doy:03d}0000_01D_01D_OSB.BIA.gz').resolve()
    folder=root/day;folder.mkdir(exist_ok=True)
    xml=ET.Element('groops');p=ET.SubElement(ET.SubElement(xml,'program'),'GnssSinexBias2SignalBias')
    for tag,value in [('outputfileSignalBias',str(folder/'signalBias.txt')),('inputfileSinexBias',str(source)),('inputfilePrn2FrequencyNumber','')]:ET.SubElement(p,tag).text=value
    for prn in range(1,33):ET.SubElement(p,'identifier').text=f'G{prn:02d}'
    config=folder/'convert.xml';ET.ElementTree(xml).write(config,encoding='utf-8',xml_declaration=True)
    with (folder/'convert.log').open('w') as log:subprocess.run([str(binary),str(config)],stdout=log,stderr=subprocess.STDOUT,check=True)
    expected=read_gps_osb(source);errors=[];count=0
    for prn,values in expected.items():
        actual={}
        for line in (folder/f'signalBias.{prn}.txt').read_text().splitlines():
            f=line.split()
            if len(f)==2 and f[0].startswith(('C','L')):
                signal=f[0][:2] if f[0].startswith('L') else f[0][:3]
                actual[signal]=float(f[1])
        for signal in ['C1C','C1W','C2W','L1','L2']:
            errors.append(abs(values.get(signal,0)-actual.get(signal,0)));count+=1
    records.append({'date':day,'provider_sha256':sha256_file(source),'compared_signal_biases':count,'maximum_difference_m':max(errors)})
report={'passed':max(r['maximum_difference_m'] for r in records)<1e-12,'native_binary_sha256':sha256_file(binary),'dates':records,
 'sign_identity':'(y + b_primary - b_active) - b_primary = y - b_active',
 'native_observation_equation':'l -= T * transmitter->antennaVariations(...); antennaVariations adds signalBias.compute(types)',
 'signal_semantics':'C1C/C1W/C2W distinct; first native phase entry per frequency after dropping attribute; missing phase bias zero',
 'scope':'Known provider datum normalization only; no observation or reference-derived bias estimate'}
write_json(Path('outputs/orbit-smoothing-poc/validation/comparison-v3/utc_osb_native_regression.json'),report)
print(json.dumps(report,indent=2))
