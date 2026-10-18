"""Prepare and inspect an explicitly NEW matched QR flight diagnostic pair.

No subprocess/native launcher. The archived coarse propagation used ordinary
arithmetic and its closure02 reference was deleted. Both new legs instead read
the same retained closure03 reference with explicit QR arithmetic. This is not
an exact-input or ordinary-to-QR replay, nor a repeated refinement experiment.
Host controls own admission, immutable runtime bindings and actual receipts.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import gates

REQUEST_SCHEMA='orbit-poc-wide-matched-flight-pair-request-v2'
IDENTITY_KEYS={'comparison_source_sha256','full_source_sha256','native_sha256','solver_sha256','source_file_count'}
ARTIFACT_KEYS={'source_freeze','controller','native_rebuild_provenance'}
OMITTED=['thermal_history_sensitivities','non_gravity_non_drag_force_gradients','atmospheric_event_time_derivatives']


def pin(path):
    return {'path':str(Path(path)),'sha256':gates.digest(path)}


def read_pin(value):
    return json.loads(gates.verify(value).read_text())


def check_terminal_audit(audit,identity,artifact_pins):
    """Accept the actual audited terminal schema, never a generic passed flag."""
    gates.require(audit.get('schema')=='orbit-poc-segmented-validation-terminal-independent-review-v1' and
        audit.get('consistency_passed') is True and audit.get('scientific_status')=='passed_scoped_checks' and
        audit.get('cleanup_verified') is True,'No independently passed actual terminal audit')
    gates.require(set(identity)==IDENTITY_KEYS and audit.get('identity')==identity,'Terminal source/native/solver identity mismatch')
    gates.require(set(artifact_pins)==ARTIFACT_KEYS,'Incomplete audited artifact binding')
    for name,value in artifact_pins.items():
        gates.require(audit.get('artifacts',{}).get(name,{}).get('sha256')==value['sha256'],
                      'Terminal '+name+' identity mismatch')


def request_file(path,sha256):
    x=read_pin({'path':str(path),'sha256':sha256})
    required={'schema','build_result','build_audit','native','decoder','historical_result','historical_xml',
              'fixed_initial','reference_orbit','input_pins','source_pins','validation_terminal_audit',
              'audited_artifacts','expected_identity','historical_attribution','output_dir','environment'}
    gates.require(set(x)==required and x['schema']==REQUEST_SCHEMA,'Unknown or missing request fields/schema')
    for key in ('native','decoder','fixed_initial','reference_orbit','historical_xml'):
        gates.verify(x[key])
    audit=read_pin(x['validation_terminal_audit'])
    check_terminal_audit(audit,x['expected_identity'],x['audited_artifacts'])
    artifacts={key:read_pin(value) for key,value in x['audited_artifacts'].items()}
    identity=x['expected_identity'];freeze=artifacts['source_freeze'];controller=artifacts['controller']
    gates.require(freeze.get('schema')=='orbit-poc-v4-validation-source-freeze-v1' and
        freeze.get('source',{}).get('sha256')==identity['full_source_sha256'] and
        len(freeze.get('source',{}).get('files',{}))==identity['source_file_count'] and
        freeze.get('comparison_source',{}).get('sha256')==identity['comparison_source_sha256'],
        'Audited source freeze mismatch')
    gates.require(controller.get('schema')=='orbit-poc-v4-cli-validation-controller-v1' and
        controller.get('status')=='passed' and controller.get('returncode')==0 and
        controller.get('interrupted_or_timeout') is False and
        controller.get('source',{}).get('sha256')==identity['full_source_sha256'], 'Audited controller mismatch')
    b=read_pin(x['build_result']);ba=read_pin(x['build_audit']);bp=artifacts['native_rebuild_provenance']
    gates.require(b.get('schema')=='orbit-poc-native-complete-build-v1' and b.get('status')=='built_complete_candidate' and
        b.get('native',{}).get('sha256')==x['native']['sha256']==identity['native_sha256'],
        'Native does not match audited complete build')
    gates.require(ba.get('schema')=='orbit-poc-native-complete-build-independent-review-v1' and ba.get('passed') is True and
        ba.get('actual_build_result',{}).get('sha256')==x['build_result']['sha256'] and
        ba.get('native',{}).get('sha256')==x['native']['sha256'] and
        ba.get('candidate_source_sha256')==b.get('candidate_source_sha256') and
        any(r.get('sha256')==x['build_audit']['sha256'] for r in audit.get('supporting_reviews',[])),
        'Actual complete build audit mismatch')
    gates.require(bp.get('schema')=='orbit-poc-v4-native-rebuild-provenance-v3' and
        bp.get('status')=='verified_actual_complete_rebuild' and
        bp.get('actual_build_result',{}).get('sha256')==x['build_result']['sha256'],'Audited build provenance mismatch')
    for key in ('input_pins','source_pins'):
        gates.require(isinstance(x[key],list) and bool(x[key]),'Empty source/input inventory')
        paths=[r['path'] for r in x[key]];gates.require(len(paths)==len(set(paths)),'Duplicate pin')
        for row in x[key]:gates.verify(row)
    source_hashes=set(freeze['source']['files'].values())
    gates.require(all(r['sha256'] in source_hashes for r in x['source_pins']) and
                  x['decoder']['sha256']==freeze['source']['files'].get('src/orbit_poc/segmented/tangent_export.py'),
                  'Source/decoder does not match audited freeze')
    historical=read_pin(x['historical_result']);attribution=read_pin(x['historical_attribution'])
    gates.require(historical.get('binary_sha256')==x['native']['sha256'],'Historical flight result used another native')
    gates.require(historical.get('physical_initial_sha256')==x['fixed_initial']['sha256'],'Fixed-state receipt mismatch')
    gates.require(historical.get('passed') is True and historical.get('status')=='complete' and
        historical.get('schema')=='flight-staged-refinement-3.1','Original flight stage did not pass')
    gates.require(historical.get('date')=='2024-04-24' and historical.get('start_utc_seconds')==42300 and
        historical.get('duration_seconds')==1800 and historical.get('code_threshold_m')==.003 and
        historical.get('carrier_threshold_m')==3e-5,'Changed historical window or refinement limits')
    gates.require(attribution.get('schema')=='orbit-poc-validation07-coarse-flight-invocation-attribution-v1' and
        attribution.get('status')=='read_only_attribution_complete' and
        attribution.get('independent_terminal_audit',{}).get('sha256')==x['validation_terminal_audit']['sha256'] and
        attribution.get('native_invocation',{}).get('native_binary_sha256')==x['native']['sha256'] and
        attribution.get('native_invocation',{}).get('config_sha256')==x['historical_xml']['sha256'],
        'Historical invocation attribution mismatch')
    known={r['source']['sha256'] for r in attribution.get('archived_records',[])}
    gates.require(x['historical_result']['sha256'] in known,'Historical result not bound by attribution')
    retained=attribution.get('retention_constraint',{});old=retained.get('missing_original_input',{})
    replacement=retained.get('retained_final_reference_candidate',{})
    gates.require(retained.get('current_missing_confirmed') is True and old.get('status')=='deleted' and
        old.get('path')!=x['reference_orbit']['path'] and old.get('sha256')!=x['reference_orbit']['sha256'] and
        all(replacement.get(k)==x['reference_orbit'][k] for k in ('path','sha256')),
        'Reference replacement not explicitly bound to retained final orbit')
    inputs={r['path']:r['sha256'] for r in x['input_pins']}
    for key in ('fixed_initial','reference_orbit'):
        gates.require(inputs.get(x[key]['path'])==x[key]['sha256'],key+' not input-pinned')
    for p,h in historical.get('physical_input_hashes',{}).items():
        gates.require(inputs.get(p)==h,'Original flight physical input missing/changed')
    for p in inputs:
        gates.require(not any(s in p.upper() for s in ('GNV1B','/NP2','/NP3')),'Reference input is in diagnostic namespace')
    env=x['environment'];gates.require(isinstance(env,dict) and all(type(k)is str and type(v)is str for k,v in env.items()),'Invalid environment')
    gates.require(env.get('ORBIT_POC_NUMERICS_QR_PREFIX')=='<LEG>/native-prefix','Explicit shared QR arithmetic is required')
    # The concrete host packet must use a sanitized environment. This adapter
    # admits only the one known arithmetic switch, never inherited overrides.
    gates.require(not any(k.startswith('ORBIT_POC_') and k!='ORBIT_POC_NUMERICS_QR_PREFIX' for k in env),
                  'Unexpected native arithmetic override')
    for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        gates.require(env.get(k)=='1','Single numerical thread required')
    gates.require(bool(env.get('HOME')),'Explicit HOME required')
    original=ET.parse(x['historical_xml']['path']).getroot()
    gates.require(original.findtext('.//OrbitPocEvaluateVariational/inputfileInitialState')==x['fixed_initial']['path'],
                  'XML does not use exact pinned fixed initial state')
    gates.require(original.findtext('./program/PreprocessingVariationalEquation/inputfileOrbit')==old['path'],
                  'Original reference input attribution mismatch')
    outputs=output_paths(original)
    for n in original.iter():
        if n.tag.startswith('inputfile') and n.text and n.text.strip().startswith('/'):
            q=n.text.strip()
            if q in outputs or q==old['path']:continue
            gates.require(q in inputs,'Unpinned absolute physical XML input')
    return x


def output_paths(root):
    return {n.text.strip() for n in root.iter() if
            (n.tag.startswith('outputfile') or n.tag=='orbitPocDerivativeDiagnostics') and n.text and n.text.strip()}


def matched_configs(original_xml,reference_before,reference_after,output_dir):
    """Relocate original outputs BEFORE rebinding the one physical reference.

    The retained closure03 reference is also an old output. Substitution in the
    opposite order would turn it into a self-reading fresh output.
    """
    old=ET.fromstring(original_xml);outputs=output_paths(old)
    gates.require(old.findtext('./program/PreprocessingVariationalEquation/inputfileOrbit')==reference_before,
                  'Unexpected original reference')
    gates.require(reference_after!=reference_before,'Reference change must be explicit')
    names=[Path(p).name for p in outputs]
    gates.require(len(names)==len(set(names)),'Output basenames collide')
    result={};canonical=[]
    for name in ('no-export','export'):
        out=Path(output_dir)/name;mapping={p:str(out/Path(p).name) for p in outputs}
        gates.require(reference_after not in mapping.values(),'Fresh output aliases retained reference')
        kwargs={} if name=='no-export' else {'export_path':out/'local-tangent.jsonl','stm_path':out/'physical-stm.txt'}
        adapted,delta=gates.flight_config(original_xml,mapping,**kwargs)
        root=ET.fromstring(adapted)
        node=root.find('./program/PreprocessingVariationalEquation/inputfileOrbit')
        gates.require(node.text==reference_before,'Output renaming changed original reference')
        node.text=reference_after
        restored=deepcopy(root)
        if name=='export':
            restored.remove(restored[-1]);p=restored.find('./program/PreprocessingVariationalEquation')
            p.remove(p.find('orbitPocSegmentedTangentExport'))
        inverse={v:k for k,v in mapping.items()}
        for n in restored.iter():
            if n.text and n.text.strip() in inverse:n.text=inverse[n.text.strip()]
        restored.find('./program/PreprocessingVariationalEquation/inputfileOrbit').text=reference_before
        gates.require(gates.semantic_xml(restored)==gates.semantic_xml(old),'Non-output/non-reference physical change')
        canonical.append(gates.semantic_xml(restored))
        result[name]={'xml':ET.tostring(root,encoding='utf-8',xml_declaration=True),'output_map':mapping,'xml_delta':delta,
            'reference_change':{'before':reference_before,'after':reference_after},'outputs':{
                'orbit_binary':root.findtext('.//OrbitPocEvaluateVariational/outputfileOrbit'),
                'derivatives':root.findtext('.//PreprocessingVariationalEquation/orbitPocDerivativeDiagnostics')}}
        converters=[p for p in root.findall('./program/FileConvert') if p.findtext('inputfile')==result[name]['outputs']['orbit_binary']]
        gates.require(len(converters)==1,'Expected saved text orbit converter')
        result[name]['outputs']['orbit_text']=converters[0].findtext('outputfile')
        if name=='export':result[name]['outputs'].update(tangent=str(out/'local-tangent.jsonl'),stm=str(out/'physical-stm.txt'))
    gates.require(canonical[0]==canonical[1],'Matched physical recipes differ')
    return result


def prepare(path,sha256):
    x=request_file(path,sha256);out=Path(x['output_dir'])
    gates.require(out.is_absolute() and '..' not in out.parts and not out.exists(),'Fresh absolute output required')
    protected=[Path(r['path']) for r in x['input_pins']+x['source_pins']]+[Path(x['historical_xml']['path'])]
    gates.require(all(out!=p and out not in p.parents and p not in out.parents for p in protected),'Output overlaps immutable evidence')
    attribution=read_pin(x['historical_attribution'])
    previous=attribution['retention_constraint']['missing_original_input']
    configs=matched_configs(Path(x['historical_xml']['path']).read_bytes(),previous['path'],x['reference_orbit']['path'],out)
    out.mkdir(parents=False);legs=[]
    for name,leg in configs.items():
        folder=out/name;folder.mkdir();config=folder/'flight.xml';config.write_bytes(leg.pop('xml'))
        env=dict(x['environment']);env['ORBIT_POC_NUMERICS_QR_PREFIX']=str(folder/'native-prefix')
        legs.append({'name':name,'config':pin(config),'argv':[x['native']['path'],str(config)],'cwd':str(folder),'environment':env,**leg})
    plan={'schema':'orbit-poc-wide-matched-flight-pair-plan-v2','request':pin(path),'legs':legs,
          'source_pins':x['source_pins'],'input_pins':x['input_pins'],'native':x['native'],
          'historical_xml':x['historical_xml'],'deleted_historical_reference':previous,'shared_retained_reference':x['reference_orbit'],
          'scope':'Fresh matched QR no-export/export pair using retained final reference; not exact-input historical replay or ordinary-to-QR equivalence.',
          'status':'prepared_not_executed','native_execution_performed':False,'scientific_pass':False,
          'historical_refinement_rerun':False,'benchmark_fit_attempts':0,
          'requires_before_launch':'Independent concrete request review and owned host admission with sanitized environment/read-only complete runtime.'}
    gates.write_fresh(out/'plan.json',plan);return plan


def check_derivatives(value):
    import math
    gates.require(value.get('profile')=='flight_gravity_drag_v1' and value.get('omitted_terms')==OMITTED and
                  value.get('maximum_tangent_relative_residual',math.inf)<=gates.RESIDUAL,'Fresh native derivative guard failed')


def check_execution_receipt(x,leg,r):
    folder=Path(x['output_dir'])/leg['name'];config=folder/'flight.xml'
    env=dict(x['environment']);env['ORBIT_POC_NUMERICS_QR_PREFIX']=str(folder/'native-prefix')
    gates.require(leg['config']['path']==str(config) and leg['cwd']==str(folder) and
        leg['argv']==[x['native']['path'],str(config)] and leg['environment']==env,
        'Planned native invocation changed')
    gates.require(r.get('schema')=='orbit-poc-matched-flight-leg-execution-v1' and
        r.get('returncode')==0 and r.get('timed_out') is False and r.get('interrupted') is False and
        r.get('config_sha256')==leg['config']['sha256'] and r.get('native_sha256')==x['native']['sha256'] and
        r.get('environment')==env and r.get('argv')==leg['argv'] and r.get('cwd')==leg['cwd'] and
        r.get('input_pins')==x['input_pins'],'Fresh matched execution attribution failed')


def inspect_pair(request_path,request_hash,plan_path,plan_hash,execution_receipts,output):
    import numpy as np
    from orbit_poc.comparison.backend import read_native_table
    x=request_file(request_path,request_hash);plan=read_pin({'path':str(plan_path),'sha256':plan_hash})
    gates.require(plan.get('schema')=='orbit-poc-wide-matched-flight-pair-plan-v2' and plan.get('request')==pin(request_path),
                  'Wrong matched pair plan')
    gates.require([r.get('name') for r in plan.get('legs',[])]==['no-export','export'] and len(execution_receipts)==2,'Missing matched legs')
    legs=plan['legs'];orbits=[];derivatives=[]
    expected=matched_configs(Path(x['historical_xml']['path']).read_bytes(),
        read_pin(x['historical_attribution'])['retention_constraint']['missing_original_input']['path'],
        x['reference_orbit']['path'],x['output_dir'])
    for leg,receipt_pin in zip(legs,execution_receipts):
        gates.verify(leg['config']);r=read_pin(receipt_pin);name=leg['name']
        gates.require(Path(leg['config']['path']).read_bytes()==expected[name]['xml'] and leg['outputs']==expected[name]['outputs'],
                      'Planned matched XML/outputs changed')
        check_execution_receipt(x,leg,r)
        orbits.append(read_native_table(leg['outputs']['orbit_text'],10))
        derivatives.append(json.loads(Path(leg['outputs']['derivatives']).read_text()));check_derivatives(derivatives[-1])
    fixed=np.loadtxt(x['fixed_initial']['path'],skiprows=2).reshape(6)
    gates.require(all(o.shape==(361,10) and np.array_equal(o[0,1:7],fixed) for o in orbits),'Fresh orbit does not preserve fixed initial state')
    gates.require(gates.digest(legs[0]['outputs']['orbit_binary'])==gates.digest(legs[1]['outputs']['orbit_binary']),
                  'Matched binary orbits differ')
    export=legs[1]['outputs'];decoder=gates.load_decoder(x['decoder'])
    result=gates.check_flight(gates.jsonl(export['tangent']),read_native_table(export['stm'],43),
        orbits[0],orbits[1],derivatives[1],read_pin(x['historical_result']),decoder,
        gates.retained_orbit_times(gates.verify(x['reference_orbit']).read_bytes()))
    result.update(schema='orbit-poc-wide-matched-flight-pair-result-v2',request=pin(request_path),plan=pin(plan_path),
        execution_receipts=execution_receipts,shared_retained_reference=x['reference_orbit'],
        historical_refinement_rerun=False,ordinary_to_qr_equivalence_claimed=False,exact_input_historical_replay=False,
        no_export_native_relative_residual=derivatives[0]['maximum_tangent_relative_residual'])
    result['output_pins']={leg['name']:{key:pin(value) for key,value in leg['outputs'].items()} for leg in legs}
    gates.write_fresh(output,result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare-flight-pair');a.add_argument('--request',required=True);a.add_argument('--sha256',required=True)
    a=sub.add_parser('check-flight-pair')
    for name in ('request','sha256','plan','plan-sha256','execution-receipts','output'):a.add_argument('--'+name,required=True)
    args=p.parse_args()
    if args.mode=='prepare-flight-pair':result=prepare(args.request,args.sha256)
    else:result=inspect_pair(args.request,args.sha256,args.plan,args.plan_sha256,json.loads(Path(args.execution_receipts).read_text()),args.output)
    print(json.dumps(result,indent=2,allow_nan=False))
if __name__=='__main__':main()
