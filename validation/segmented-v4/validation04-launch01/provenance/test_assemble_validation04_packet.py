import importlib.util,json,sys
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('assembler',Path(__file__).with_name('assemble_validation04_packet.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.mark.parametrize('fault',['failed_review','changed_patch_map','wrong_candidate_path','wrong_candidate_hash'])
def test_unbound_review_rejected_before_output(tmp_path,monkeypatch,fault):
 rows=[]
 for i,name in enumerate(sorted(m.ALLOWED)):
  p=tmp_path/f'p{i}';p.write_text(str(i));rows.append({'relative':name,'path':str(p),'sha256':m.sha(p),'bytes':p.stat().st_size})
 manifest=tmp_path/'candidate.json';manifest.write_text(json.dumps(rows));mapping={x['relative']:{k:x[k] for k in ('path','sha256')} for x in rows}
 review={'passed':True,'patched_files':mapping,'candidate_files':{'path':str(manifest),'sha256':m.sha(manifest)}}
 if fault=='failed_review':review['passed']=False
 elif fault=='changed_patch_map':review['patched_files']={}
 elif fault=='wrong_candidate_path':review['candidate_files']['path']=str(tmp_path/'other')
 else:review['candidate_files']['sha256']='0'*64
 rp=tmp_path/'review.json';rp.write_text(json.dumps(review));output=tmp_path/'packet';monkeypatch.setattr(m,'P',output);monkeypatch.setattr(m,'C',output/'control');monkeypatch.setattr(m,'OLD',tmp_path/'missing-original')
 monkeypatch.setattr(sys,'argv',['assemble','--review',str(rp),'--review-sha256',m.sha(rp),'--patch-manifest',str(manifest),'--patch-manifest-sha256',m.sha(manifest)])
 with pytest.raises(AssertionError):m.main()
 assert not output.exists()
