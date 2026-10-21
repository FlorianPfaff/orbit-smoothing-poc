"""Standalone exact/wildcard final-symlink fixtures; only a fresh temporary directory."""
import argparse,hashlib,importlib.util,json,platform,tempfile,types,uuid
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(helper):
    spec=importlib.util.spec_from_file_location('d03_prepare_alias_test',helper);p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
    with tempfile.TemporaryDirectory(prefix='d03-preparer02-alias-') as directory:
        root=Path(directory);folder=root/'links';folder.mkdir();files=root/'data';files.mkdir()
        canonical=Path('/orbit-d03-nonexistent-alias-'+uuid.uuid4().hex);assert not canonical.exists()
        for name in ('synthetic_accuracy.xml','G01.xml'):
            (files/name).write_text('exact original '+name);(folder/name).symlink_to(canonical/name)
            assert (folder/name).is_symlink() and not (folder/name).exists()
        def mapped(path,e):
            path=Path(path)
            return files/path.relative_to(canonical) if path==canonical or canonical in path.parents else path
        def resolved(path,e):
            path=Path(path)
            return mapped(path.readlink(),e) if path.is_symlink() else path.resolve()
        d=types.SimpleNamespace(host_path=mapped,resolved_host_path=resolved);results=[]
        for mask,count in [('synthetic_accuracy.xml',1),('{prn}.xml',2)]:
            profile=root/'profile.xml';profile.write_text('<groops><inputfileMetadata>'+str(folder/mask)+'</inputfileMetadata></groops>')
            inputs,links,identity=p.collect_inputs(profile,{},d)
            assert len(inputs)==count+1 and len(links)==count
            rows=identity['inputs'][0]['files'];assert len(rows)==count
            assert all(Path(row['resolved']['path']).parent==files and row['resolved']['sha256']==sha(row['resolved']['path']) for row in rows)
            results.append({'mask':mask,'matched_final_symlinks':count,'resolved_hashes_verified':True})
        return {'schema':'orbit-poc-d03-prepare-alias-fixtures-v1','passed':True,'python':platform.python_version(),'helper':{'path':str(helper),'sha256':sha(helper)},'cases':results,'scientific_validation_complete':False,'scope':'Temporary exact/wildcard final symlinks unresolved on host, resolved through explicit aliases; no source/data/native workload.'}
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--helper',type=Path,required=True);a.add_argument('--helper-sha256',required=True);a.add_argument('--output',type=Path,required=True);args=a.parse_args()
    assert sha(args.helper)==args.helper_sha256
    result=run(args.helper)
    with args.output.open('x') as f:json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps(result))
