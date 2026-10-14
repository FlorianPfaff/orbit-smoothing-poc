"""Check native reflector-frame/sign conventions without testing orbit accuracy."""
from __future__ import annotations
import argparse,json,os,subprocess,time
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation,Slerp
from orbit_poc.comparison.data import _gps1b_text,sha256_file,write_json


def table(path):
    return np.loadtxt(path,skiprows=2)


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--star-camera',type=Path,required=True);p.add_argument('--groops',required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    manifest=json.loads(args.manifest.read_text());root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    baseline=table(manifest['predictions']);base_xml=ET.parse(manifest['configs']['predict_slr'])
    # For this local geometry-only test keep covariance computation disabled.
    for parent in base_xml.iter():
        for child in list(parent):
            if child.tag=='outputfilePredictiveCovariance':parent.remove(child)
    source_info=Path(base_xml.find('.//satellite/satellites/inputfileSatelliteInfo').text)
    sca=np.array([[float(row[0]),*map(float,row[3:7])] for row in map(str.split,_gps1b_text(args.star_camera)[1])])
    # The native converter stores scalar-first q as SRF-to-CRF using exactly
    # the standard active quaternion matrix; do not invert it from header prose.
    seconds=(baseline[:,0]-51544.5)*86400
    rotations=Slerp(sca[:,0]-sca[0,0],Rotation.from_quat(sca[:,[2,3,4,1]]))(seconds-sca[0,0]).as_matrix()
    step=.01;checks=[]
    for axis in range(3):
        values=[]
        for sign in (-1,1):
            info=ET.parse(source_info);node=info.find('.//equipment/position/'+('xyz'[axis]));node.text=str(float(node.text)+sign*step)
            out=root/f'axis{axis}_{sign:+d}.xml';info.write(out)
            config=ET.fromstring(ET.tostring(base_xml.getroot()))
            config.find('.//satellite/satellites/inputfileSatelliteInfo').text=str(out)
            predictions=root/f'predictions_axis{axis}_{sign:+d}.txt'
            config.find('.//outputfilePredictions').text=str(predictions)
            xml=root/f'predict_axis{axis}_{sign:+d}.xml';ET.ElementTree(config).write(xml)
            with (root/f'axis{axis}_{sign:+d}.log').open('w') as log:
                subprocess.run([args.groops,str(xml)],stdout=log,stderr=subprocess.STDOUT,check=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
            values.append(table(predictions)[:,3])
        derivative=(values[1]-values[0])/(2*step)
        expected=-np.einsum('ni,ni->n',baseline[:,10:13],rotations[:,:,axis])
        delta=derivative-expected
        # Attitude is evaluated at transmitted rather than exact reflection time
        # here (few milliseconds); 1e-4 derivative tolerance is conservative.
        checks.append({'axis_srf':'xyz'[axis],'max_abs_derivative_difference':float(np.max(abs(delta))),
                       'rms_derivative_difference':float(np.sqrt(np.mean(delta**2))),'passed':bool(np.max(abs(delta))<1e-4)})
    result={'purpose':'native sign/frame validation only; bootstrap trajectory, no scientific orbit accuracy claim',
            'normal_points':len(baseline),'reflector_perturbation_m':step,'checks':checks,
            'passed':all(x['passed'] for x in checks),'binary_sha256':sha256_file(args.groops),
            'slr_manifest_sha256':sha256_file(args.manifest),'star_camera_sha256':sha256_file(args.star_camera),
            'derivative_definition':'d(observed-minus-modeled)/d(SRF reflector offset) = -J_position * R_SRF_to_CRF',
            'approximation':'independent quaternion interpolation at transmit time; native geometry uses reflection time',
            'range_bias_sign_check':None}
    write_json(root/'summary.json',result);print(json.dumps(result,indent=2))

if __name__=='__main__':main()
