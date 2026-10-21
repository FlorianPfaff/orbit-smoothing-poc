"""Bounded, immutable checkpoints for four generators and twelve prefix preparations."""
from dataclasses import asdict
from pathlib import Path
from . import protocol as p
from .multiday import native_data_inventory


def worker(job,directory):
    """One concrete native preparation component, supervised like every worker."""
    from .multiday import generate_continuous_case,prepare_one
    options={**job['options'],'groops_executable':job['runtime']['native']['path'],'retain_native_diagnostics':True}
    p.verify_artifact({'path':options['tudat_python'],'sha256':options['tudat_python_sha256']})
    if job['component']=='generation':
        case={**job['case']['case'],'duration_hours':72,'coverage':'normal'};case.pop('mask',None)
        value=generate_continuous_case(case,job['output'],options)
    elif job['component']=='prefix':
        record=p.read_json(p.verify_artifact(job['generation']))
        if record.get('status')!='prepared':raise ValueError('Prefix requires a sealed successful generation')
        value=prepare_one(job['case'],Path(job['output']),job['runtime'],options,record['record'])
    else:raise ValueError('Unknown preparation component')
    return {'status':'prepared','record':value,'component':job['component']}


def component(config,plan,root,project,runtime,name,kind,case,output,generation=None):
    directory=root/'preparation-jobs'/name
    job={'operation':'prepare_component','component':kind,'case':case,'output':str(output),'options':asdict(config.preparation),'runtime':runtime,'plan_hash':plan['plan_hash'],'generation':generation}
    digest=p.canonical_hash(job);index=directory/'checkpoint.json'
    if directory.exists():
        if not index.is_file():raise p.NotReady('Partial or failed preparation component is preserved: '+str(directory))
        checkpoint=p.read_json(index);result=p.read_json(p.verify_artifact(checkpoint['result']))
        if p.read_json(directory/'request.json')!=job or checkpoint.get('job_hash')!=digest or result.get('status')!='prepared' or result.get('component')!=kind:raise ValueError('Preparation checkpoint attribution differs')
        inventory=p.read_json(p.verify_artifact(checkpoint['output_inventory']))
        if inventory!=native_data_inventory(output):raise ValueError('Preparation checkpoint output membership or bytes changed')
        p.verify_nested_artifacts(result['record'])
        if generation:p.verify_artifact(generation)
        return checkpoint['result'],result['record']
    if Path(output).exists():raise p.NotReady('Unsealed partial preparation output is preserved: '+str(output))
    p.admission(config,root,project);directory.mkdir(parents=True);p.write_json(directory/'request.json',job)
    try:
        result=p._execute_job(job,directory,runtime,config.resources)
    except BaseException as error:
        p.write_json(directory/'failure.json',{'status':'interrupted_or_failed','error':type(error).__name__+': '+str(error),'job_hash':digest})
        raise
    path=directory/'execution.json';p.write_json(path,result)
    if result.get('status')!='prepared' or result.get('component')!=kind or result.get('harness_execution',{}).get('owned_process_group_cleaned') is not True:raise p.NotReady('Preparation component failed; preserve '+str(path))
    p.verify_nested_artifacts(result['record'])
    inventory=directory/'output-inventory.json';p.write_json(inventory,native_data_inventory(output))
    p.write_json(index,{'schema':'orbit-poc-segmented-preparation-checkpoint-v1','job_hash':digest,'result':p.artifact(path),'output_inventory':p.artifact(inventory)})
    return p.artifact(path),result['record']


def prepare_inputs(config,plan,root,project,runtime,flight):
    """No catalog-wide deadline: each component has its own resource budget."""
    generated={};prefixes={};entries=[];base=root/'preparation'
    for case in plan['cases']:
        if case['stage']=='flight':
            request=p.wrap_flight_request(flight[case['case_id']],base/'flight-reference'/case['case_id'])
        else:
            gid=case['generation_id']
            if gid not in generated:
                generated[gid]=component(config,plan,root,project,runtime,gid,'generation',case,base/'generation'/gid)[0]
            key=p.canonical_hash({'stage':case['stage'],'case':case['case']})
            if key not in prefixes:
                prefixes[key]=component(config,plan,root,project,runtime,'prefix-'+key,'prefix',case,base/'prefixes'/key,generated[gid])[1]
            request={**prefixes[key],'method':case['method'],'parameters':case['parameters']}
        path=base/'requests'/(case['case_id']+'.json')
        if path.exists() and p.read_json(path)!=request:raise ValueError('Prepared request checkpoint changed')
        if not path.exists():p.write_json(path,request)
        entries.append({'case_id':case['case_id'],'request':p.artifact(path)})
    return {'schema':'orbit-poc-segmented-input-catalog-v1','entries':entries}
