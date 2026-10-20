"""Prepare the unchanged fixture variant only after audited pilot reconciliation."""
from pathlib import Path
import argparse,datetime,hashlib,importlib.util,json,math,xml.etree.ElementTree as ET
from reconcile_pilot05 import verify_for_preparation
B=Path('/home/emper/orbit-nuisance-warmstarts')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p),'bytes':Path(p).stat().st_size}
def save(p,v):
    with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def main():
    a=argparse.ArgumentParser()
    for name in ('reconciliation','reconciliation-audit','pilot-control','output'):a.add_argument('--'+name,type=Path,required=True)
    a.add_argument('--parent-preparation',type=Path,default=B/'profiles-prepared01/preparation.json')
    args=a.parse_args();OUT=args.output.absolute()
    reconciliation,module=verify_for_preparation(args.reconciliation,args.reconciliation_audit,args.pilot_control)
    original_result=Path(reconciliation['original_result']['path'])
    assert not OUT.exists() and OUT.resolve()==OUT and not OUT.is_relative_to(original_result.parent)
    parent=args.parent_preparation;prep=json.loads(parent.read_text());parentpin=pin(parent)
    assert not OUT.is_relative_to(parent.resolve().parent)
    for item in prep['copies']:
        assert sha(item['copy'])==item['copy_sha256'] and Path(item['copy']).stat().st_size==item['bytes']
    OUT.mkdir();changes=[]
    for group in prep['groups']:
        for point in group['points']:
            old=Path(point['profile_template']['path']);assert sha(old)==point['profile_template']['sha256'];d=OUT/group['name']/point['name'];d.mkdir(parents=True)
            text=old.read_text();new=text.replace(str(old.parent)+'/',str(d)+'/')
            if group['nuisance_prior_variant']:
                new=module.transform(text,old.parent,d)
                point['declared_changes'].extend({'path':name+'/selectTransmitters/all','before':'absent (empty selection)','after':'explicit all','scope':'Dedicated native datum-prior fixture only, piloted separately; primary inputs and production model unchanged'} for name in ('codeBiases','tecBiases'))
            else:assert new.replace(str(d)+'/',str(old.parent)+'/')==text
            target=d/'template.xml';target.write_text(new)
            # Inputs remain identical. Only output location and the declared
            # native test-fixture selections may differ from its parent.
            root=ET.fromstring(new)
            for element in root.iter():
                if (element.tag.startswith('outputfile') or element.attrib.get('label')=='tmpDir') and element.text:
                    assert Path(element.text.strip()).resolve().is_relative_to(d)
            for mapping in point['remapping']:
                if mapping['new'].startswith(str(old.parent)+'/'):mapping['new']=str(d)+mapping['new'][len(str(old.parent)):]
            point['profile_template']={**pin(target),'is_symlink':False,'resolved_path':str(target)}
            changes.append({'group':group['name'],'point':point['name'],'original_template':pin(old),'new_template':pin(target),'explicit_native_transmitter_selection':group['nuisance_prior_variant']})
    assert pin(parent)==parentpin
    verify_for_preparation(args.reconciliation,args.reconciliation_audit,args.pilot_control)
    prep.update(created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),runner=pin(__file__),source_preparation=parentpin,prior_fixture_pilot=reconciliation['original_result'],prior_fixture_pilot_control=pin(args.pilot_control),prior_fixture_reconciliation=pin(args.reconciliation),prior_fixture_reconciliation_audit=pin(args.reconciliation_audit),fixture_revision='explicit_native_transmitter_bias_selection_v3',scope='Separate corrected fixture preparation: primary pulse/density models, masks and input bytes unchanged; native code/TEC datum-prior fixture explicitly selects transmitter biases. Failed original fixture and pilot retained.')
    save(OUT/'preparation.json',prep);save(OUT/'changes.json',{'changes':changes,'parent':parentpin,'original_pilot_result':reconciliation['original_result'],'reconciliation':pin(args.reconciliation),'reconciliation_audit':pin(args.reconciliation_audit),'primary_scientific_inputs_unchanged':True,'release_authority':False})
    print(json.dumps({'preparation':pin(OUT/'preparation.json'),'templates':len(changes),'audited_reconciled_native_prior_feasibility':True,'original_pilot_reported_passed':False}))
if __name__=='__main__':main()
