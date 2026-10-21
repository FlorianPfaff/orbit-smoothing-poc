#!/usr/bin/env python3
"""Derive fresh outer controls after two audited zero-fit setup failures.

A separately audited fresh seal adds exactly three original OSB dependencies.
All scientific inputs, source/runtime bytes and constraints remain unchanged.
This writes metadata; the existing controller still performs all live checks.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import socket

B = Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
OLD = B / 'fit-campaign-control-07'
NEW = B / 'fit-campaign-control-09'
BIN = B / 'bwrap-cap-01/binaries/bwrap-0.6.1-ubuntu0.3-maxargs16384'
WRAPPER = B / 'bwrap-cap-01/controls/with_segmented_fit_namespace05.py'
KEYS = {'schema', 'helper', 'original_assembly', 'original_capture',
        'failure_review', 'build_review', 'wrapper_review', 'wrapper',
        'bubblewrap', 'control', 'intervening_capture', 'intervening_review', 'probe_review', 'smoke_failure_capture', 'smoke_failure_review', 'normalization_smoke_capture', 'normalization_smoke_review', 'normalization_census', 'fresh_seal', 'fresh_seal_review', 'fresh_sealing_plan', 'fresh_readonly_plan'}
ORIGINAL_ASSEMBLY = 'ad6a3a51dc556bad83ca460bb5354ae6a3bed26b7bbed359d8388598650e180b'
ORIGINAL_CAPTURE = '20c14ed104f0a7e1dd3f270f29fd43ceb0e59922d9ccb3535d5a19abcf15dbc0'
FAILURE_REVIEW = 'ec5c3054379336adf322c775fe1a5db6324daeaf6ba10eeb172bbf621f6732e9'
INTERVENING_CAPTURE = 'cd831883bd951e2d36deadd1f8cadd0954e9ed5daa5c4e785226868d5785325d'
INTERVENING_REVIEW = 'd265125968abe3f28da92294124ed19f4294814764acacc9ccbf6f5ab5732e9b'
SMOKE_CAPTURE = '993e9100571bcf31989c80eb161e2c80475f152a51ca4b52a8b1c77080d201b0'
SMOKE_REVIEW = 'b642da2208c2843c888125731dc44fc629aa80d5348fa853727867eb33b12e46'
BOOTSTRAP_SHA = '34d7566e5dce85971a878bacaddb7be7d8a3aee37f76831717245b484c794a34'
OUTPUTS = ('invocation.json', 'host-plan.json', 'launch-pins.json',
           'host-view-plan.json', 'recovery.json', 'failure.json')


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def pin(path):
    return {'path': str(path), 'sha256': sha(path)}


def checked(value):
    need(isinstance(value, dict) and set(value) == {'path', 'sha256'}, 'Exact pin required')
    path = Path(value['path'])
    need(path.is_absolute() and path.is_file() and sha(path) == value['sha256'], 'Pinned control changed: ' + str(path))
    return path


def read(value):
    return json.loads(checked(value).read_text())


def module(name, value):
    spec = importlib.util.spec_from_file_location(name, checked(value))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return pin(path)


def process_gone(identity):
    try:
        fields = (Path('/proc') / str(identity['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
    except FileNotFoundError:
        return True
    return int(fields[19]) != identity['start_ticks'] or fields[0] == 'Z'


def empty_writables(mount):
    rows = mount['writable_mounts']
    need(len(rows) == 3 and {row['kind'] for row in rows} == {'attempts', 'temporary', 'lock'}, 'Original writable set differs')
    for row in rows:
        path = Path(row['source'])
        stat = path.stat()
        need(not path.is_symlink() and (stat.st_dev, stat.st_ino) == (row['identity']['device'], row['identity']['inode']), 'Writable identity changed')
        if row['kind'] == 'lock':
            need(path.is_file() and stat.st_size == 0, 'Original statistical lock changed')
        else:
            need(path.is_dir() and not any(path.iterdir()), 'A fit or private output already exists')


def fresh_control(control):
    need(set(control) == {'path', 'device', 'inode'} and control['path'] == str(NEW), 'Fresh canonical09 control required')
    stat = NEW.stat()
    need(NEW.is_dir() and not NEW.is_symlink() and str(NEW.resolve()) == str(NEW) and (stat.st_dev, stat.st_ino) == (control['device'], control['inode']), 'Fresh control identity changed')
    need(all(not (NEW / name).exists() and not (NEW / name).is_symlink() for name in (*OUTPUTS, 'pipeline.json', 'campaign-launch.json', 'campaign-driver.log')), 'Preserve earlier recovery output')


def accepted_correction(request, build_review, wrapper_review):
    need(build_review['status'] == 'accepted_cap_only_control_build' and build_review['binary'] == request['bubblewrap'], 'Control build lacks exact independent acceptance')
    need(wrapper_review['bootstrap_sha256'] == BOOTSTRAP_SHA, 'Wrapper bootstrap identity differs')
    need(wrapper_review['status'] == 'accepted_checked_private_dev_bootstrap' and wrapper_review['wrapper'] == request['wrapper'] and wrapper_review['bubblewrap'] == request['bubblewrap'], 'Wrapper lacks exact independent acceptance')


def accepted_probe(request, review, old_invocation, allowlist_sha256):
    need(review['status'] == 'accepted_actual_private_dev_namespace_probe' and review['wrapper'] == request['wrapper'] and review['bubblewrap'] == request['bubblewrap'], 'Exact actual alias probe acceptance required')
    need(review['mount_plan'] == old_invocation['mount_plan'] and review['allowlist_sha256'] == allowlist_sha256 and review['probe_spec'] == old_invocation['probe_spec'], 'Actual probe must use exact audited fresh sealed inputs')
    need(review['probe_status'] == 'passed' and review['benchmark_attempts_launched'] == 0 and review['cleanup_verified'] is True and review['attempts_empty'] is True and review['temporary_empty'] is True, 'Actual probe did not leave a clean zero-fit boundary')
    need(review['bootstrap_sha256'] == BOOTSTRAP_SHA, 'Actual bootstrap identity differs')
    bootstrap = read(review['bootstrap_receipt'])
    expected_command = [old_invocation['taskset']['path'], '-c', '24', old_invocation['python']['path'], '-B', old_invocation['probe_helper']['path'], '--spec', old_invocation['probe_spec']['path'], '--sha256', old_invocation['probe_spec']['sha256'], '--allowlist-sha256', review['allowlist_sha256'], '--mount-plan-sha256', old_invocation['mount_plan']['sha256'], '--expected-completed', '0']
    command_sha = hashlib.sha256(b''.join(x.encode() + b'\0' for x in expected_command)).hexdigest()
    need(bootstrap['schema'] == 'orbit-poc-private-dev-bootstrap-result-v1' and bootstrap['status'] == 'passed' and bootstrap['bootstrap_sha256'] == BOOTSTRAP_SHA and bootstrap['original_command_preserved'] is True, 'Actual checked bootstrap did not pass')
    need(bootstrap['command'] == expected_command and bootstrap['original_command_sha256'] == command_sha and bootstrap['descriptors'] == [], 'Actual bootstrap command or descriptors differ')
    need(len(bootstrap['removed']) == 2 and {r['path'] for r in bootstrap['removed']} == {'/dev/shm', '/dev/core'} and next(r for r in bootstrap['removed'] if r['path'] == '/dev/core')['target'] == '/proc/kcore', 'Actual bootstrap removal scope differs')
    need(set(bootstrap['namespaces']) == set(bootstrap['outer_namespaces']) == {'mnt', 'pid', 'net'} and all(bootstrap['namespaces'][k] != bootstrap['outer_namespaces'][k] for k in ('mnt', 'pid', 'net')), 'Actual bootstrap namespace is not fresh')
    proof = read(review['proof'])
    execution = read(review['execution'])
    need(proof['status'] == 'passed' and proof['benchmark_attempts_launched'] == 0 and proof['fit_execution_authorized'] is False and proof['specification_file_sha256'] == old_invocation['probe_spec']['sha256'], 'Actual probe proof differs')
    need(proof['host_verified_final_artifacts'] == {'allowlist_sha256': review['allowlist_sha256'], 'mount_plan_sha256': old_invocation['mount_plan']['sha256'], 'expected_completed': 0} and proof['public_readonly_checks']['terminal_prefix'] == [] and proof['public_readonly_checks']['validation']['status'] == 'passed', 'Actual public probe attribution differs')
    need(execution['bootstrap'] == review['bootstrap_receipt'], 'Execution and bootstrap attribution differ')
    need(execution['status'] == 'passed' and execution['fit_attempts'] == 0 and execution['cleanup']['verified'] is True and execution['cleanup']['live_owned_processes'] == [] and not execution['interrupted_or_timeout'], 'Actual smoke execution is not clean')


def verified_intervening(request):
    need(request['intervening_capture']['sha256'] == INTERVENING_CAPTURE and request['intervening_review']['sha256'] == INTERVENING_REVIEW, 'Intervening failure attribution differs')
    capture = read(request['intervening_capture'])
    audit = read(request['intervening_review'])
    need(audit['status'] == 'verified_terminal_setup_failure_zero_fits' and audit['final_cleanup_verified'] is True and audit['fit_attempts_started'] == audit['fit_attempts_completed'] == 0 and audit['actual_inner_proof_passed'] is False, 'Intervening failure not independently clean')
    need(capture['status'] == 'controller_failed' and capture['fit_attempts'] == 0 and capture['attempts_empty'] and capture['temporary_empty'] and not capture['prelaunch_probe_present'], 'Wrong intervening zero-fit capture')
    for row in capture['files']:
        checked({key: row[key] for key in ('path', 'sha256')})
    need(all(process_gone(row) for row in capture['owned_identities']), 'An intervening owned process remains live')
    return capture


def verified_smoke_failure(request):
    need(request['smoke_failure_capture']['sha256'] == SMOKE_CAPTURE and request['smoke_failure_review']['sha256'] == SMOKE_REVIEW, 'Prior actual smoke identity differs')
    capture = read(request['smoke_failure_capture'])
    review = read(request['smoke_failure_review'])
    need(capture['status'] == 'failed' and capture['fit_attempts'] == 0 and capture['attempts_empty'] and capture['temporary_empty'], 'Wrong prior actual smoke boundary')
    need(review['status'] == 'verified_failed_actual_namespace_probe' and review['cleanup_verified'] is True and review['benchmark_attempts_launched'] == 0 and review['actual_full_namespace_probe_passed'] is False, 'Prior actual smoke lacks failure audit')
    for row in capture['files']:
        checked({key: row[key] for key in ('path', 'sha256')})
    execution = read(review['execution'])
    need(execution['status'] == 'failed' and execution['fit_attempts'] == 0 and execution['cleanup']['verified'] is True and execution['cleanup']['live_owned_processes'] == [], 'Prior actual smoke cleanup differs')
    need(all(process_gone(row) for row in execution['cleanup']['identities']), 'Prior actual smoke process is live')
    return capture


def derive(old_invocation, old_host, old_launch, old_view, wrapper, bubblewrap, control, fresh_invocation, fresh_readonly_plan):
    """Return only the permitted coordinate-preserving outer metadata deltas."""
    need(old_host['control_root'] == old_launch['control_root'] == str(OLD), 'Wrong failed campaign')
    need(old_host['wrapper'] == old_invocation['wrapper'], 'Old invocation/wrapper differ')
    need(old_view['mount_plan'] == old_invocation['mount_plan'], 'Old mount attribution differs')
    need(old_invocation['resume_planner'] is None, 'No fit may be resumed or replaced')
    need(wrapper['path'] == str(WRAPPER) and bubblewrap['path'] == str(BIN), 'Unexpected corrected controls')
    need(control == str(NEW), 'Explicit fresh campaign09 required')
    need(set(fresh_invocation)==set(old_invocation), 'Fresh invocation options differ')
    need(all(fresh_invocation[k]==old_invocation[k] for k in old_invocation if k not in ('mount_plan','inner_plan','probe_spec')), 'Fresh invocation changes scientific/helper identity')
    invocation = copy.deepcopy(fresh_invocation)
    invocation.update(wrapper=wrapper, bubblewrap=bubblewrap)
    host = copy.deepcopy(old_host)
    host.update(control_root=control, wrapper=wrapper)
    launch = copy.deepcopy(old_launch)
    launch['control_root'] = control
    view = copy.deepcopy(old_view)
    view['mount_plan']=fresh_invocation['mount_plan']
    view['readonly_plan']=fresh_readonly_plan
    return invocation, host, launch, view


OLD_SEAL = B / 'fit-seal-control-07/sealed-inputs-03'
NEW_SEAL = B / 'fit-seal-control-07/sealed-inputs-04'
OLD_RESULT_SHA = 'd7d83bec057d06020d2ec51d23905026fe7b074967e239898e0b8f42eafcb09a'
CENSUS_SHA = '1cf15d472fb1f1cc9e7f89e0b434a2011a34f2a47984fefb151280027ca3da12'
COLLECTOR_SHA = '62c3e34437867b5063b91a66547bb26a7d501dc639ca122192427823aed7ffb0'
SEALER_SHA = 'ece54c60d011e3ef8ee252d9a424d35dc1862a1069246e7c0bf8f4b950ace776'
FRESH_PLAN_SHA = 'e97df59a680762ac718a60cd3ff75abc9a81bc429581c4702b515a5b532b4734'
FRESH_READONLY_SHA = '489f4752ab6129496ff2e61ee8d5f5f524cc9f140f4f7fe8878095a68f383e99'
OSB_SHA = '027f0f0568634f44e7b8ce414dc506b0a9becc338f4e832d45ce25f8065de54b'
NORMALIZATION_SMOKE_CAPTURE = '0ecfe5bacc920b887b9906604f0fbb6ce4d3ba5ce09750cfef9dd91cc1329934'
NORMALIZATION_SMOKE_REVIEW = '947332207ea215765f5cae7943dc510d3bb08a5f997aba11be5a57ef30507a50'
SEAL_ARTIFACTS = {'allowlist-core-plan.json','allowlist-core.json','allowlist-plan.json','allowlist.json','backing-map.json','correspondence.json','inner-plan.json','invocation.json','mount-input.json','mount-plan.json','probe-spec.json','safe-tree-00.json','safe-tree-01.json','safe-tree-02.json','skeleton-request.json','support-core.json','support-final.json'}


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def census_rows(census):
    need(census['schema']=='orbit-poc-public-verifier-read-closure-census-v1' and census['required_file_count']==43961 and census['covered_count']==43958 and census['missing_count']==3 and census['different_hash_count']==0 and census['different_hash']==[], 'Exact public verifier census required')
    rows=census['missing'];need(len(rows)==3 and len({r['path'] for r in rows})==3, 'Exactly three unique OSB additions required')
    for r in rows:
        need(r['classification']=='namespace_file_absent' and r['denied_matches']==[] and r['host_matches_expected'] is True and r['sha256']==r['host_sha256']==OSB_SHA and r['host_bytes']==125584 and r['namespace_resolved']==r['path'], 'OSB census identity differs')
    return {r['path']:r for r in rows}


def load_seal(value,root):
    need(value['path']==str(root/'result.json'), 'Exact sealed result path required')
    result=read(value);need(set(result['artifacts'])==SEAL_ARTIFACTS, 'Sealed artifact membership differs')
    data={};metadata={}
    for name,q in result['artifacts'].items():
        need(q['path']==str(root/name), 'Unexpected sealed artifact path')
        path=checked(q);s=path.stat()
        metadata[str(path)]={**q,'bytes':s.st_size,'device':s.st_dev,'inode':s.st_ino,'mode':s.st_mode&0o7777}
        if not name.startswith('safe-tree-'):data[name]=json.loads(path.read_text())
    skeleton=root/'run-skeleton';s=skeleton.stat();need(skeleton.is_dir() and not skeleton.is_symlink(), 'Exact fresh skeleton required')
    metadata[str(skeleton)]={'path':str(skeleton),'device':s.st_dev,'inode':s.st_ino}
    return {'root':str(root),'result':result,'data':data,'metadata':metadata}


def compare_seals(old,new,census):
    """Allow three measured data exposures and regenerated named metadata only."""
    additions=census_rows(census);paths=set(additions)
    for bundle in (old,new):
        r=bundle['result'];need(r['status']=='sealed_metadata' and r['fit_attempts']==r['native_executions']==0 and r['fit_execution_authorized'] is False, 'Seal is not a zero-fit metadata result')
        need(set(r['artifacts'])==SEAL_ARTIFACTS, 'Unexpected seal artifact set')
        for name,key in [('allowlist-core.json','allowlist_hash'),('allowlist.json','allowlist_hash'),('mount-plan.json','mount_plan_hash')]:
            v=bundle['data'][name];need(v[key]==canonical({k:x for k,x in v.items() if k!=key}), 'Sealed content digest differs')
        m=bundle['data']['mount-plan.json'];payload=b''.join(v.encode()+b'\0' for v in m['mount_args'])
        need(m['mount_args_payload']=={'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload),'encoding':'nul-terminated-utf8'}, 'Mount argument payload differs')
    for name in ('safe-tree-00.json','safe-tree-01.json','safe-tree-02.json'):
        need(old['result']['artifacts'][name]['sha256']==new['result']['artifacts'][name]['sha256'], 'Frozen source/runtime inventory changed')
    need(new['result']['manifest']==old['result']['manifest'] and new['result']['manifest_hash']==old['result']['manifest_hash'], 'Scientific manifest changed')
    def normalize(bundle,value):
        root=bundle['root'];meta=bundle['metadata'];hashes={v['sha256']:'@metadata-sha/'+Path(p).name for p,v in meta.items() if 'sha256' in v}
        for name,key in [('allowlist-core.json','allowlist_hash'),('allowlist.json','allowlist_hash'),('mount-plan.json','mount_plan_hash')]:hashes[bundle['data'][name][key]]='@content-sha/'+name
        def walk(v):
            if isinstance(v,str):
                if v in hashes:return hashes[v]
                return '@seal'+v[len(root):] if v==root or v.startswith(root+'/') else v
            if isinstance(v,list):return [walk(x) for x in v]
            if not isinstance(v,dict):return v
            found=meta.get(v.get('path'));out={}
            for k,x in v.items():
                if found and k in ('sha256','bytes','device','inode','mode'):
                    need(k in found and found[k]==x, 'Generated metadata identity differs: '+v['path']+' '+k)
                    out[k]='@metadata-'+k+'/'+Path(v['path']).name
                else:out[walk(k)]=walk(x)
            return out
        return walk(value)
    def file_rows(name,kind):
        for bundle in (old,new):
            rows=bundle['data'][name]['files'];need(len(rows)==len({r[kind] for r in rows}), 'Duplicate sealed file identity')
        before=old['data'][name]['files'];after=new['data'][name]['files']
        fresh={r[kind]:r for r in after if r[kind] in paths}
        need(set(fresh)==paths and not paths&{r[kind] for r in before}, 'Measured OSB membership differs')
        for p,r in fresh.items():
            c=additions[p]
            if kind=='canonical':
                b=r['backing'];need(set(r)=={'canonical','backing'} and b['path']==c['host_backing'] and b['sha256']==OSB_SHA and b['bytes']==125584 and b['device']==c['host_device'] and b['inode']==c['host_inode'] and b['mode']==c['host_lstat_mode']&0o7777, 'OSB physical backing differs')
            else:
                expected={'path':p,'resolved':p,'link_target':None,'device':c['host_device'],'inode':c['host_inode'],'bytes':125584,'sha256':OSB_SHA}
                if name.startswith('allowlist'):expected['reasons']=['verification_metadata_or_required_native_dependency']
                need(r==expected, 'OSB allowlist row differs')
        retained=[r for r in after if r[kind] not in paths]
        need(len(before)==len(retained), 'Existing sealed file membership changed')
        for a,b in zip(before,retained):
            if a[kind] in old['metadata']:
                need(b[kind] in new['metadata'] and normalize(old,a)==normalize(new,b), 'Generated sealed file changed unexpectedly')
            else:
                # Scientific and external control rows must remain byte-for-byte
                # identical even if their digest equals a metadata artifact.
                need(a==b, 'Existing support/data/control file changed')
    for name in ('support-core.json','support-final.json','allowlist-core.json','allowlist.json'):file_rows(name,'path')
    file_rows('backing-map.json','canonical')
    # Existing paths are compared exactly after only named generated metadata
    # identities are normalized. No directory-prefix exemption for input bytes.
    for name in old['data']:
        a=copy.deepcopy(old['data'][name]);b=copy.deepcopy(new['data'][name])
        if name in ('support-core.json','support-final.json','allowlist-core.json','allowlist.json'):
            a.pop('files');b.pop('files')
        if name=='backing-map.json':a.pop('files');b.pop('files')
        if name=='probe-spec.json':
            need(paths<=set(b['protected_readonly_targets']) and not paths&set(a['protected_readonly_targets']), 'OSB probe readonly targets missing')
            b['protected_readonly_targets']=[x for x in b['protected_readonly_targets'] if x not in paths]
        if name=='correspondence.json':b['protected_readonly_targets']-=3
        if name=='mount-plan.json':
            fresh=[r for r in b['readonly_mounts'] if r['target'] in paths]
            need(len(fresh)==3 and {r['target'] for r in fresh}==paths, 'Exactly three new readonly file mounts required')
            for r in fresh:need(r=={'operation':'ro-bind','source':additions[r['target']]['host_backing'],'target':r['target'],'kind':'file'}, 'OSB readonly mount differs')
            b['readonly_mounts']=[r for r in b['readonly_mounts'] if r['target'] not in paths]
            for p in paths:
                need(p not in a['verified_file_backings'] and p in b['verified_file_backings'], 'OSB file backing membership differs')
                need(b['verified_file_backings'].pop(p)==next(r['backing'] for r in new['data']['backing-map.json']['files'] if r['canonical']==p), 'Mount/OSB backing differs')
            def operations(args):
                widths={'--unshare-user':0,'--unshare-pid':0,'--unshare-net':0,'--unshare-ipc':0,'--unshare-uts':0,'--die-with-parent':0,'--new-session':0,'--clearenv':0,'--cap-drop':1,'--tmpfs':1,'--dir':1,'--ro-bind':2,'--symlink':2,'--proc':1,'--dev':1,'--bind':2,'--setenv':2,'--chdir':1,'--remount-ro':1};out=[];i=0
                while i<len(args):
                    need(args[i] in widths,'Unknown namespace operation');n=widths[args[i]]+1;need(i+n<=len(args),'Truncated namespace operation');out.append(args[i:i+n]);i+=n
                return out
            oldops=operations(a.pop('mount_args'));newops=operations(b.pop('mount_args'));oldirs={normalize(old,x[1]) for x in oldops if x[0]=='--dir'};parents={str(x) for p in paths for x in Path(p).parents}
            reduced=[];removed=0
            for op in newops:
                if op[0]=='--ro-bind' and op[2] in paths:
                    need(op[1]==additions[op[2]]['host_backing'],'OSB argument backing differs');removed+=1;continue
                if op[0]=='--dir' and normalize(new,op[1]) not in oldirs:
                    need(op[1] in parents,'Unrelated new namespace directory');continue
                reduced.append(op)
            need(removed==3 and normalize(old,oldops)==normalize(new,reduced),'Original namespace operation/order changed')
            a.pop('mount_args_payload');b.pop('mount_args_payload')
        need(normalize(old,a)==normalize(new,b),'Unexpected sealed metadata delta: '+name)
    a=copy.deepcopy(old['result']);b=copy.deepcopy(new['result']);b['files']-=3;b['conditional_host_correspondence']['protected_readonly_targets']-=3
    need(normalize(old,a)==normalize(new,b),'Unexpected seal result delta')
    return {'old_root':old['root'],'fresh_root':new['root'],'added_files':[additions[p] for p in sorted(paths)],'scientific_manifest':old['result']['manifest'],'manifest_hash':old['result']['manifest_hash'],'existing_file_identities_unchanged':True,'source_runtime_inventory_hashes_unchanged':True,'denials_unchanged':True,'writable_identities_unchanged':True,'namespace_order_preserved':True}


def compare_sealing_controls(old_plan,plan,old_base,base,old_parents,parents,fresh_plan_pin):
    """Permit only the reviewed collector/sealer and named output relocation."""
    need(set(plan)==set(old_plan), 'Sealing plan options changed')
    need(set(base)==set(old_base), 'Readonly plan options changed')
    need(base['payload']=={'helper':plan['request']['helper'],'mode':'seal_inputs','plan':fresh_plan_pin}, 'Fresh readonly payload differs')
    for key in base:
        if key not in ('payload','parent_topology'):need(base[key]==old_base[key],'Readonly admission/mapping changed: '+key)
    need(parents==old_parents, 'Readonly parent topology changed')
    for key in plan:
        if key not in ('request','planned_outputs'):need(plan[key]==old_plan[key], 'Sealing plan scientific/admission metadata changed: '+key)
    need(set(plan['planned_outputs'])==set(old_plan['planned_outputs']), 'Sealing output membership changed')
    for name,p in plan['planned_outputs'].items():
        need(p==str(NEW_SEAL/name) and old_plan['planned_outputs'][name]==str(OLD_SEAL/name), 'Sealing output relocation differs')
    before=copy.deepcopy(old_plan['request']);after=copy.deepcopy(plan['request'])
    need(after['output_root']==str(NEW_SEAL) and before['output_root']==str(OLD_SEAL), 'Fresh seal roots differ')
    need(after['helper']=={'path':str(B/'fit-seal-control-07/seal_direct_fit_inputs05.py'),'sha256':SEALER_SHA} and after['helpers']['allowlist']=={'path':str(B/'fit-seal-control-07/prepare_segmented_fit_allowlist04.py'),'sha256':COLLECTOR_SHA}, 'Unreviewed normalization sealing helpers')
    before.pop('helper');after.pop('helper');before.pop('output_root');after.pop('output_root');before['helpers'].pop('allowlist');after['helpers'].pop('allowlist')
    need(before==after,'Scientific or unrelated sealing request changed')


def accepted_fresh_seal(request,old_view):
    census=read(request['normalization_census']);need(request['normalization_census']['sha256']==CENSUS_SHA,'Measured census changed')
    need(request['fresh_sealing_plan']=={'path':str(B/'fit-seal-control-07/sealing-plan05.json'),'sha256':FRESH_PLAN_SHA} and request['fresh_readonly_plan']=={'path':str(B/'fit-seal-control-07/readonly-view-plan06.json'),'sha256':FRESH_READONLY_SHA}, 'Exact reviewed fresh sealing controls required')
    old=load_seal({'path':str(OLD_SEAL/'result.json'),'sha256':OLD_RESULT_SHA},OLD_SEAL)
    new=load_seal(request['fresh_seal'],NEW_SEAL)
    review=read(request['fresh_seal_review'])
    need(review['status']=='accepted_exact_normalization_support_seal' and review['old_result']=={'path':str(OLD_SEAL/'result.json'),'sha256':OLD_RESULT_SHA} and review['fresh_result']==request['fresh_seal'] and review['census']==request['normalization_census'] and review['collector_sha256']==COLLECTOR_SHA and review['cleanup_verified'] is True and review['scientific_inputs_unchanged'] is True,'Fresh seal requires exact independent audit')
    delta=compare_seals(old,new,census)
    need(review['added_paths']==sorted(r['path'] for r in delta['added_files']), 'Seal audit addition scope differs')
    old_base=read(old_view['readonly_plan']);base=read(request['fresh_readonly_plan']);old_plan=read(old_base['payload']['plan']);plan=read(request['fresh_sealing_plan'])
    need(review['sealing_plan']==request['fresh_sealing_plan'] and review['readonly_plan']==request['fresh_readonly_plan'],'Seal review controls differ')
    compare_sealing_controls(old_plan,plan,old_base,base,read(old_base['parent_topology']),read(base['parent_topology']),request['fresh_sealing_plan'])
    checked(plan['request']['helper']);checked(plan['request']['helpers']['allowlist'])
    return old,new,delta


def verified_normalization_failure(request):
    need(request['normalization_smoke_capture']['sha256']==NORMALIZATION_SMOKE_CAPTURE and request['normalization_smoke_review']['sha256']==NORMALIZATION_SMOKE_REVIEW,'Normalization failure attribution differs')
    capture=read(request['normalization_smoke_capture']);review=read(request['normalization_smoke_review'])
    need(capture['status']=='failed' and capture['fit_attempts']==0 and capture['attempts_empty'] and capture['temporary_empty'],'Normalization failure boundary differs')
    need(review['status']=='verified_failed_actual_namespace_probe' and review['actual_bootstrap_passed'] is True and review['actual_full_namespace_probe_passed'] is False and review['cleanup_verified'] is True and review['benchmark_attempts_launched']==0,'Normalization failure audit differs')
    for row in capture['files']:checked({k:row[k] for k in ('path','sha256')})
    execution=read(review['execution']);need(execution['status']=='failed' and execution['fit_attempts']==0 and execution['cleanup']['verified'] is True and execution['cleanup']['live_owned_processes']==[],'Normalization failure cleanup differs')
    need(all(process_gone(row) for row in execution['cleanup']['identities']),'Normalization failure process remains live')
    return capture


def context(request):
    need(set(request) == KEYS and request['schema'] == 'orbit-poc-campaign09-normalization-recovery-request-v1', 'Unknown recovery options')
    need(request['helper'] == pin(Path(__file__).resolve()), 'Recovery helper changed')
    need(request['original_assembly'] == {'path': str(OLD / 'assembly.json'), 'sha256': ORIGINAL_ASSEMBLY}, 'Original assembly differs')
    need(request['original_capture']['sha256'] == ORIGINAL_CAPTURE and request['failure_review']['sha256'] == FAILURE_REVIEW, 'Original terminal audit differs')
    assembly = read(request['original_assembly'])
    capture = read(request['original_capture'])
    audit = read(request['failure_review'])
    need(audit['status'] == 'verified_setup_failure_no_fits' and audit['cleanup_verified'] is True and audit['fit_attempts'] == 0 and audit['actual_inner_proof_passed'] is False, 'No audited zero-fit boundary')
    need(capture['status'] == 'controller_failed' and capture['fit_attempts'] == 0 and capture['attempts_empty'] and capture['temporary_empty'] and not capture['prelaunch_probe_present'], 'Wrong terminal capture')
    for row in capture['files']:
        checked({key: row[key] for key in ('path', 'sha256')})
    need(all(process_gone(row) for row in capture['owned_identities']), 'An original owned process remains live')
    intervening = verified_intervening(request)
    smoke_failure = verified_smoke_failure(request)
    normalization_failure = verified_normalization_failure(request)
    old_host = read(assembly['artifacts']['host-plan.json'])
    old_launch = read(assembly['artifacts']['launch-pins.json'])
    old_view = read(assembly['artifacts']['host-view-plan.json'])
    old_invocation = read(old_host['invocation'])
    need(old_host['host'] == {'hostname': socket.gethostname(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}, 'Original host/boot changed')
    mount = read(old_invocation['mount_plan'])
    empty_writables(mount)
    fresh_control(request['control'])
    binary = checked(request['bubblewrap'])
    wrapper = checked(request['wrapper'])
    need(str(binary) == str(BIN) and str(wrapper) == str(WRAPPER), 'Unreviewed control paths')
    build_review = read(request['build_review'])
    wrapper_review = read(request['wrapper_review'])
    accepted_correction(request, build_review, wrapper_review)
    old_seal,new_seal,seal_delta=accepted_fresh_seal(request,old_view)
    fresh_invocation=new_seal['data']['invocation.json']
    accepted_probe(request, read(request['probe_review']), fresh_invocation,new_seal['result']['artifacts']['allowlist.json']['sha256'])
    wrapper_module = module('corrected_fit_wrapper', request['wrapper'])
    need(wrapper_module.EXPECTED_BUBBLEWRAP == request['bubblewrap'] and wrapper_module.BOOTSTRAP_SHA256 == BOOTSTRAP_SHA, 'Wrapper fixed binary/bootstrap identity differs')
    host_module = module('unchanged_host_controller', old_host['helper'])
    need(host_module.load_plan(assembly['artifacts']['host-plan.json']['path'], assembly['artifacts']['host-plan.json']['sha256']) == old_host, 'Original host context differs')
    return assembly, capture, intervening, smoke_failure, normalization_failure, old_invocation, old_host, old_launch, old_view, host_module, new_seal, seal_delta


def assemble(request):
    assembly, capture, intervening, smoke_failure, normalization_failure, old_invocation, old_host, old_launch, old_view, host_module, new_seal, seal_delta = context(request)
    invocation, host, launch, view = derive(old_invocation, old_host, old_launch, old_view, request['wrapper'], request['bubblewrap'], str(NEW), new_seal['data']['invocation.json'],request['fresh_readonly_plan'])
    artifacts = {}
    def save(name, value):
        result = write_new(NEW / name, value)
        artifacts[name] = result
        return result
    try:
        host['invocation'] = save('invocation.json', invocation)
        launch['plan'] = save('host-plan.json', host)
        need(host_module.load_plan(launch['plan']['path'], launch['plan']['sha256']) == host, 'Unchanged host rejected recovery')
        view['launch_pins'] = save('launch-pins.json', launch)
        view_pin = save('host-view-plan.json', view)
        module('unchanged_host_view', view['helper']).build(view)
        for row in capture['files'] + intervening['files'] + smoke_failure['files'] + normalization_failure['files']:
            checked({key: row[key] for key in ('path', 'sha256')})
        result = {'schema': 'orbit-poc-campaign09-normalization-recovery-result-v1', 'status': 'assembled_metadata',
                  'request': request, 'artifacts': artifacts, 'manifest_hash': assembly['manifest_hash'],
                  'original_mount_plan': old_invocation['mount_plan'], 'fresh_mount_plan': invocation['mount_plan'], 'seal_delta': seal_delta, 'unchanged_original_invocation': old_host['invocation'],
                  'fit_attempts': 0, 'native_executions': 0, 'fit_execution_authorized': False,
                  'launch_command': ['/usr/bin/taskset', '-c', '32', host['control_python']['path'], '-B', view['helper']['path'], '--plan', view_pin['path'], '--sha256', view_pin['sha256']],
                  'scope': 'Control recovery with exactly three census-pinned historical OSB exposures and regenerated named sealing metadata. All original scientific input bytes, source/runtime identities, inner/probe helpers, denials, writable identities and fit order remain unchanged. Failed campaigns07/08 and actual smokes01/02 are retained. Wrapper05 retains six existing-library aliases and uses a checked bootstrap to remove only fresh private shm/core defaults before the unchanged command. Actual campaign inner proof remains mandatory.'}
        save('recovery.json', result)
        return result
    except BaseException as error:
        write_new(NEW / 'failure.json', {'status': 'failed', 'error': repr(error), 'artifacts': artifacts, 'fit_attempts': 0, 'native_executions': 0})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    result = assemble(read({'path': args.request, 'sha256': args.sha256}))
    print(json.dumps({key: result[key] for key in ('status', 'manifest_hash', 'fit_attempts', 'launch_command')}))


if __name__ == '__main__':
    main()
