"""Author tests: reduced actual shapes, no host mutation or scientific execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

C=Path('/mnt/d/orbit-segmented-v4/control')
spec=importlib.util.spec_from_file_location('normalization_recovery',Path(__file__).with_name('derive_campaign09_normalization03.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def recalc(bundle):
    d=bundle['data'];previous={}
    for name,key in [('allowlist-core.json','allowlist_hash'),('allowlist.json','allowlist_hash')]:
        v=d[name];old=v[key];v[key]=m.canonical({k:x for k,x in v.items() if k!=key});previous[old]=v[key]
    def replace(v):
        if isinstance(v,str):return previous.get(v,v)
        if isinstance(v,list):return [replace(x) for x in v]
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        return v
    for n,v in d.items():
        if n not in ('allowlist-core.json','allowlist.json'):d[n]=replace(v)
    v=d['mount-plan.json'];raw=b''.join(x.encode()+b'\0' for x in v['mount_args'])
    v['mount_args_payload']={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'encoding':'nul-terminated-utf8'}
    v['mount_plan_hash']=m.canonical({k:x for k,x in v.items() if k!='mount_plan_hash'})

@pytest.fixture(scope='module')
def base_pair():
    p=C/'direct-sealing05-terminal01/sealed'
    result=json.loads((p/'result.json').read_text())
    data={n:json.loads((p/n).read_text()) for n in m.SEAL_ARTIFACTS if not n.startswith('safe-tree-')}
    root=str(m.OLD_SEAL)
    generated={str(m.OLD_SEAL/n) for n in ('inner-plan.json','probe-spec.json')}
    # Keep actual frozen representative data, helper and generated control rows.
    selected={r['path'] for r in data['support-core.json']['files'][:2]}|generated
    selected|={r['path'] for r in data['support-core.json']['files'] if r['path'].endswith('/probe_segmented_fit_namespace02.py')}
    metadata={str(m.OLD_SEAL/n):{**q,'bytes':100,'device':2048,'inode':1000+i,'mode':384} for i,(n,q) in enumerate(result['artifacts'].items())}
    for r in data['backing-map.json']['files']:
        if r['canonical'] in generated:metadata[r['canonical']]=copy.deepcopy(r['backing'])
    skeleton=data['backing-map.json']['run_skeleton'];metadata[root+'/run-skeleton']=copy.deepcopy(skeleton)
    def collect_metadata(v):
        if isinstance(v,list):
            for x in v:collect_metadata(x)
        if isinstance(v,dict):
            if isinstance(v.get('path'),str) and v['path'] in metadata:
                for k in ('bytes','device','inode','mode'):
                    if k in v:metadata[v['path']][k]=v[k]
            for x in v.values():collect_metadata(x)
    collect_metadata(data)
    for n in ('support-core.json','support-final.json','allowlist-core.json','allowlist.json'):
        data[n]['files']=[r for r in data[n]['files'] if r['path'] in selected]
    data['backing-map.json']['files']=[r for r in data['backing-map.json']['files'] if r['canonical'] in selected]
    mount=data['mount-plan.json'];mount['readonly_mounts']=[r for r in mount['readonly_mounts'] if r['kind']!='file' or r['target'] in selected]
    mount['verified_file_backings']={k:v for k,v in mount['verified_file_backings'].items() if k in selected}
    data['probe-spec.json']['protected_readonly_targets']=[r['target'] for r in mount['readonly_mounts']]
    # Retain argument order and structural operations, omitting only fixture-pruned files.
    args=mount['mount_args'];out=[];i=0
    widths={'--unshare-user':0,'--unshare-pid':0,'--unshare-net':0,'--unshare-ipc':0,'--unshare-uts':0,'--die-with-parent':0,'--new-session':0,'--clearenv':0,'--cap-drop':1,'--tmpfs':1,'--dir':1,'--ro-bind':2,'--symlink':2,'--proc':1,'--dev':1,'--bind':2,'--setenv':2,'--chdir':1,'--remount-ro':1}
    allowed={(r['source'],r['target']) for r in mount['readonly_mounts']}
    while i<len(args):
        op=args[i:i+1+widths[args[i]]];i+=len(op)
        if op[0]=='--ro-bind' and (op[1],op[2]) not in allowed:continue
        out+=op
    mount['mount_args']=out
    old={'root':root,'result':result,'data':data,'metadata':metadata};recalc(old)
    # Construct a hypothetical freshly sealed metadata bundle, not an actual receipt.
    new=copy.deepcopy(old);newroot=str(m.NEW_SEAL)
    hashes={v['sha256']:hashlib.sha256(('fresh '+Path(k).name).encode()).hexdigest() for k,v in metadata.items() if 'sha256' in v and not Path(k).name.startswith('safe-tree-')}
    def rebase(v):
        if isinstance(v,str):
            if v in hashes:return hashes[v]
            return newroot+v[len(root):] if v==root or v.startswith(root+'/') else v
        if isinstance(v,list):return [rebase(x) for x in v]
        if isinstance(v,dict):
            out={rebase(k):rebase(x) for k,x in v.items()}
            if v.get('path') in metadata:
                for k in ('bytes','inode'):
                    if k in out:out[k]+=100
            return out
        return v
    new=rebase(new);new['root']=newroot
    census=json.loads((C/'public-verifier-closure-census01/summary01.json').read_text())
    for c in census['missing']:
        path=c['path'];r={'path':path,'resolved':path,'link_target':None,'device':c['host_device'],'inode':c['host_inode'],'bytes':125584,'sha256':m.OSB_SHA}
        for n in ('support-core.json','support-final.json','allowlist-core.json','allowlist.json'):
            row=copy.deepcopy(r)
            if n.startswith('allowlist'):row['reasons']=['verification_metadata_or_required_native_dependency']
            new['data'][n]['files'].append(row);new['data'][n]['files'].sort(key=lambda v:v['path'])
        backing={'path':c['host_backing'],'bytes':125584,'sha256':m.OSB_SHA,'device':c['host_device'],'inode':c['host_inode'],'mode':c['host_lstat_mode']&0o7777}
        new['data']['backing-map.json']['files'].append({'canonical':path,'backing':backing});new['data']['backing-map.json']['files'].sort(key=lambda v:v['canonical'])
        d=new['data'];d['probe-spec.json']['protected_readonly_targets'].append(path)
        mt=d['mount-plan.json'];mt['readonly_mounts'].append({'operation':'ro-bind','source':c['host_backing'],'target':path,'kind':'file'});mt['verified_file_backings'][path]=backing
        pos=mt['mount_args'].index('--remount-ro');mt['mount_args'][pos:pos]=['--ro-bind',c['host_backing'],path]
    new['data']['correspondence.json']['protected_readonly_targets']+=3
    new['result']['files']+=3;new['result']['conditional_host_correspondence']['protected_readonly_targets']+=3
    recalc(new)
    return old,new,census

@pytest.fixture
def pair(base_pair):return copy.deepcopy(base_pair)

def test_exact_three_additions_and_relocated_named_metadata(pair):
    before=copy.deepcopy(pair);delta=m.compare_seals(*pair)
    assert pair==before and len(delta['added_files'])==3
    assert all(delta[k] for k in ('existing_file_identities_unchanged','source_runtime_inventory_hashes_unchanged','denials_unchanged','writable_identities_unchanged','namespace_order_preserved'))

@pytest.mark.parametrize('name', ['support-core.json','support-final.json','allowlist-core.json','allowlist.json','backing-map.json'])
def test_existing_file_hash_immutable(pair,name):
    r=pair[1]['data'][name]['files'][0]
    if name=='backing-map.json':r=r['backing']
    r['sha256']='0'*64;recalc(pair[1])
    with pytest.raises(ValueError):m.compare_seals(*pair)

@pytest.mark.parametrize('field,value',[('inode',999),('device',999),('bytes',1),('resolved','/elsewhere'),('link_target','/elsewhere')])
def test_existing_data_identity_immutable(pair,field,value):
    pair[1]['data']['support-core.json']['files'][0][field]=value;recalc(pair[1])
    with pytest.raises(ValueError):m.compare_seals(*pair)

@pytest.mark.parametrize('key,value',[('schema','other'),('required_file_count',43962),('missing_count',2),('different_hash_count',1),('different_hash',[{'path':'/x'}])])
def test_wrong_census_rejected(pair,key,value):
    pair[2][key]=value
    with pytest.raises(ValueError):m.compare_seals(*pair)

@pytest.mark.parametrize('key,value',[('classification','allowed'),('denied_matches',['/truth']),('host_matches_expected',False),('host_sha256','0'*64),('host_bytes',1),('namespace_resolved','/elsewhere')])
def test_wrong_census_identity_rejected(pair,key,value):
    pair[2]['missing'][0][key]=value
    with pytest.raises(ValueError):m.compare_seals(*pair)

@pytest.mark.parametrize('kind',['extra_file','missing_osb','duplicate','wrong_reason','wrong_backing','writable','writable_target','denied','config','safe_tree','manifest','readonly_extra','args_change','arg_unknown','extra_directory','metadata_inode','unrelated_metadata','result_status','fit_started','authorize'])
def test_scope_changes_rejected(pair,kind):
    old,new,census=pair;d=new['data'];path=census['missing'][0]['path']
    if kind=='extra_file':d['support-core.json']['files'].append({**d['support-core.json']['files'][0],'path':'/new/unreviewed'})
    if kind=='missing_osb':d['support-core.json']['files']=[r for r in d['support-core.json']['files'] if r['path']!=path]
    if kind=='duplicate':d['support-core.json']['files'].append(copy.deepcopy(d['support-core.json']['files'][0]))
    if kind=='wrong_reason':next(r for r in d['allowlist.json']['files'] if r['path']==path)['reasons']=['broad_allow']
    if kind=='wrong_backing':next(r for r in d['backing-map.json']['files'] if r['canonical']==path)['backing']['path']='/changed'
    if kind=='writable':d['mount-plan.json']['writable_mounts'][0]['identity']['inode']+=1
    if kind=='writable_target':d['mount-plan.json']['writable_mounts'][0]['target']='/changed'
    if kind=='denied':d['probe-spec.json']['denied_paths'].pop()
    if kind=='config':d['invocation.json']['config']['sha256']='0'*64
    if kind=='safe_tree':new['result']['artifacts']['safe-tree-00.json']['sha256']='0'*64
    if kind=='manifest':new['result']['manifest_hash']='0'*64
    if kind=='readonly_extra':d['mount-plan.json']['readonly_mounts'].append({'operation':'ro-bind','source':'/host','target':'/host','kind':'file'})
    if kind=='args_change':d['mount-plan.json']['mount_args'][0]='--unshare-net'
    if kind=='arg_unknown':d['mount-plan.json']['mount_args'].extend(['--unknown'])
    if kind=='extra_directory':d['mount-plan.json']['mount_args'].extend(['--dir','/unrelated-new-directory'])
    if kind=='metadata_inode':next(r for r in d['support-final.json']['files'] if r['path'].endswith('/inner-plan.json'))['inode']+=1
    if kind=='unrelated_metadata':d['inner-plan.json']['new_runtime_option']=True
    if kind=='result_status':new['result']['status']='pending'
    if kind=='fit_started':new['result']['fit_attempts']=1
    if kind=='authorize':new['result']['fit_execution_authorized']=True
    recalc(new)
    with pytest.raises(ValueError):m.compare_seals(*pair)

@pytest.fixture
def controls():
    load=lambda folder,name:json.loads((C/folder/name).read_text())
    return [load('direct-sealing05-plan-readback01','sealing-plan04.json'),load('direct-sealing06-plan-readback01','sealing-plan05.json'),load('direct-sealing05-plan-readback01','readonly-view-plan05.json'),load('direct-sealing06-plan-readback01','readonly-view-plan06.json'),load('direct-sealing05-plan-readback01','readonly-view-plan05-parents.json'),load('direct-sealing06-plan-readback01','readonly-view-plan06-parents.json'),{'path':str(m.B/'fit-seal-control-07/sealing-plan05.json'),'sha256':m.FRESH_PLAN_SHA}]

def test_actual_reviewed_controls_only_relocate_sealing_outputs(controls):
    before=copy.deepcopy(controls);m.compare_sealing_controls(*controls);assert controls==before

@pytest.mark.parametrize('kind',['helper','collector','config','wrapper','taskset','writable','denial','output','output_extra','plan_manifest','plan_native','view_mapping','view_extra','payload','parents'])
def test_unrelated_control_deltas_rejected(controls,kind):
    p=controls[1];r=p['request'];v=controls[3]
    if kind=='helper':r['helper']['sha256']='0'*64
    if kind=='collector':r['helpers']['allowlist']['sha256']='0'*64
    if kind=='config':r['config']['sha256']='0'*64
    if kind=='wrapper':r['helpers']['wrapper']['sha256']='0'*64
    if kind=='taskset':r['taskset']['sha256']='0'*64
    if kind=='writable':r['attempts']['inode']+=1
    if kind=='denial':r['additional_denied_trees']=['/changed']
    if kind=='output':p['planned_outputs']['result.json']='/elsewhere'
    if kind=='output_extra':p['planned_outputs']['new']='new'
    if kind=='plan_manifest':p['manifest_hash']='0'*64
    if kind=='plan_native':p['native_executions']=1
    if kind=='view_mapping':v['directories'].pop(next(iter(v['directories'])))
    if kind=='view_extra':v['new']=True
    if kind=='payload':v['payload']['mode']='run'
    if kind=='parents':controls[5]['new']=True
    with pytest.raises(ValueError):m.compare_sealing_controls(*controls)

def test_fresh_invocation_cannot_change_scientific_fields():
    old=json.loads((C/'direct-sealing05-terminal01/sealed/invocation.json').read_text())
    load=lambda n:json.loads((C/'campaign-assembly07-packet01/actual-readback'/n).read_text())
    args=[old,load('host-plan.json'),load('launch-pins.json'),load('host-view-plan.json'),{'path':str(m.WRAPPER),'sha256':'a'*64},{'path':str(m.BIN),'sha256':'b'*64},str(m.NEW),copy.deepcopy(old),{'path':'/fresh/view','sha256':'c'*64}]
    for key in old:
        if key in ('mount_plan','inner_plan','probe_spec'):continue
        changed=copy.deepcopy(args);changed[7][key]='modified'
        with pytest.raises(ValueError):m.derive(*changed)


def test_generated_hash_alias_cannot_change_scientific_file(pair):
    old,new,census=pair
    before=old['data']['support-core.json']['files'][0]
    after=next(r for r in new['data']['support-core.json']['files'] if r['path']==before['path'])
    before['sha256']=old['result']['artifacts']['inner-plan.json']['sha256']
    after['sha256']=new['result']['artifacts']['inner-plan.json']['sha256']
    with pytest.raises(ValueError,match='Existing support/data/control file changed'):m.compare_seals(*pair)

@pytest.fixture
def fresh_review_context(pair,controls,monkeypatch):
    old,new,census=pair
    req={'normalization_census':{'path':'/census','sha256':m.CENSUS_SHA},'fresh_seal':{'path':str(m.NEW_SEAL/'result.json'),'sha256':'f'*64},'fresh_seal_review':{'path':'/review','sha256':'e'*64},'fresh_sealing_plan':controls[6],'fresh_readonly_plan':{'path':str(m.B/'fit-seal-control-07/readonly-view-plan06.json'),'sha256':m.FRESH_READONLY_SHA}}
    view={'readonly_plan':{'path':'/old-view','sha256':'d'*64}}
    review={'status':'accepted_exact_normalization_support_seal','old_result':{'path':str(m.OLD_SEAL/'result.json'),'sha256':m.OLD_RESULT_SHA},'fresh_result':copy.deepcopy(req['fresh_seal']),'census':copy.deepcopy(req['normalization_census']),'collector_sha256':m.COLLECTOR_SHA,'cleanup_verified':True,'scientific_inputs_unchanged':True,'added_paths':sorted(r['path'] for r in census['missing']),'sealing_plan':copy.deepcopy(req['fresh_sealing_plan']),'readonly_plan':copy.deepcopy(req['fresh_readonly_plan'])}
    docs={'/census':census,'/review':review,'/old-view':controls[2],req['fresh_readonly_plan']['path']:controls[3],controls[2]['payload']['plan']['path']:controls[0],req['fresh_sealing_plan']['path']:controls[1],controls[2]['parent_topology']['path']:controls[4],controls[3]['parent_topology']['path']:controls[5]}
    monkeypatch.setattr(m,'read',lambda p:copy.deepcopy(docs[p['path']]))
    monkeypatch.setattr(m,'load_seal',lambda p,root:copy.deepcopy(old if root==m.OLD_SEAL else new))
    checked=[];monkeypatch.setattr(m,'checked',lambda p:checked.append(p))
    return req,view,review,checked

def test_review_required_in_addition_to_actual_semantic_comparison(fresh_review_context):
    req,view,review,checked=fresh_review_context
    old,new,delta=m.accepted_fresh_seal(req,view)
    assert len(delta['added_files'])==3 and {q['sha256'] for q in checked}=={m.SEALER_SHA,m.COLLECTOR_SHA}

@pytest.mark.parametrize('field',['status','old_result','fresh_result','census','collector_sha256','cleanup_verified','scientific_inputs_unchanged','added_paths','sealing_plan','readonly_plan'])
def test_fresh_seal_review_cannot_claim_different_evidence(fresh_review_context,field):
    req,view,review,checked=fresh_review_context
    if isinstance(review[field],dict):review[field]['sha256']='0'*64
    elif isinstance(review[field],bool):review[field]=False
    elif isinstance(review[field],list):review[field]=[]
    else:review[field]='unaccepted'
    with pytest.raises(ValueError):m.accepted_fresh_seal(req,view)

def test_actual_second_failed_smoke_stays_preserved(monkeypatch):
    capture=json.loads((C/'loader-alias-smoke-terminal02/manifest.json').read_text())
    review=json.loads((C/'device-bootstrap-smoke-terminal-independent-review02.json').read_text())
    execution=json.loads((C/'loader-alias-smoke-terminal02/execution/execution.json').read_text())
    req={'normalization_smoke_capture':{'path':'/capture','sha256':m.NORMALIZATION_SMOKE_CAPTURE},'normalization_smoke_review':{'path':'/review','sha256':m.NORMALIZATION_SMOKE_REVIEW}}
    docs={'/capture':capture,'/review':review,review['execution']['path']:execution}
    monkeypatch.setattr(m,'read',lambda p:copy.deepcopy(docs[p['path']]))
    checked=[];monkeypatch.setattr(m,'checked',lambda p:checked.append(p));monkeypatch.setattr(m,'process_gone',lambda p:True)
    assert m.verified_normalization_failure(req)==capture and checked
    monkeypatch.setattr(m,'process_gone',lambda p:False)
    with pytest.raises(ValueError):m.verified_normalization_failure(req)

@pytest.mark.parametrize('field',['normalization_smoke_capture','normalization_smoke_review'])
def test_second_failed_smoke_identity_cannot_be_replaced(field):
    req={'normalization_smoke_capture':{'path':'/capture','sha256':m.NORMALIZATION_SMOKE_CAPTURE},'normalization_smoke_review':{'path':'/review','sha256':m.NORMALIZATION_SMOKE_REVIEW}}
    req[field]['sha256']='0'*64
    with pytest.raises(ValueError):m.verified_normalization_failure(req)
