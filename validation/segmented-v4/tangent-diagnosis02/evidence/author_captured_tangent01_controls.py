from pathlib import Path
c=Path('/mnt/d/orbit-segmented-v4/control')
s=(c/'run_tangent_capture_build03.py').read_text().replace('orbit-poc-tangent-capture-build-plan-v1','orbit-poc-captured-tangent-plan-v1').replace('orbit-poc-owned-tangent-capture-build-v1','orbit-poc-owned-captured-tangent-v1').replace("{'original_build_manifest','recipe_inspection','capture_header','capture_block','reader_source','reader_manifest','reader_tangent','reader_force','reader_quadrature'}","{'capture','capture_result','reader_source','reader_manifest','reader_tangent','reader_force','reader_quadrature','build_result'}")
(c/'run_captured_tangent01.py').write_text(s)
s=(c/'stage_nominal_tangent_capture04.py').read_text()
s=s.replace("D=B/'tangent-telemetry-02'","D=B/'tangent-standalone-01'")
s=s.replace("{'source':str(B/'tangent-capture-03'),'target':str(B/'tangent-capture-03')}]","{'source':str(B/'tangent-capture-03'),'target':str(B/'tangent-capture-03')},{'source':str(B/'tangent-telemetry-02'),'target':str(B/'tangent-telemetry-02')}]")
s=s.replace('run_nominal_tangent_capture01.py','run_captured_tangent01.py').replace('replay_nominal_tangent_capture01.py','replay_captured_tangent01.py').replace('orbit-poc-nominal-tangent-capture-plan-v1','orbit-poc-captured-tangent-plan-v1').replace('orbit-poc-nominal-tangent-capture-staging-v1','orbit-poc-captured-tangent-staging-v1')
start=s.index("original=R/'run/preparation/prefixes'");end=s.index("p={'schema':",start)
s=s[:start]+"""inputs={}
for name,relative in [('capture',str(B/'tangent-telemetry-02/run/replay/captured-system.bin')),('capture_result',str(B/'tangent-telemetry-02/run/replay/result.json')),('build_result',str(B/'tangent-capture-03/run/build-result/result.json')),('reader_source',str(C/'reader/replay.cpp')),('reader_manifest',str(C/'reader/include/manifest.json')),('reader_tangent',str(C/'reader/include/sixStateTangent.h')),('reader_force',str(C/'reader/include/syntheticForceDerivatives.h')),('reader_quadrature',str(C/'reader/include/eventQuadrature.h'))]:inputs[name]=pin(relative)
assert inputs['capture']['sha256']=='b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2'
built=json.loads(Path(inputs['build_result']['path']).read_text());assert built['status']=='built_diagnostic_only';native=Path(built['native']['path']);assert pin(native)==built['native']
""" +s[end:]
s=s.replace("e['reserved_cpu_note']='One exact72h telemetry-only operator capture plus standalone diagnostic onCPU24/one thread/8GiB/2h. Separate capture binary with mandatory original-object baseline byte match; original inputs/profile/thresholds. No fits. Protected6000 and original150WSL untouched.'","e['reserved_cpu_note']='One pinned standalone diagnostic compiled and executed onCPU24/one thread/8GiB/2h. Captured physical operator remains read-only. No GROOPS propagation/fits; protected6000 and original150WSL untouched.'")
s=s.replace("'semantic_delta':'Capture-only native diagnostic on the original fixed72h inputs, followed by separately instrumented standalone solver telemetry. Same limits and mathematical operator; no correction, fitting or acceptance promotion.'","'semantic_delta':'Standalone reader diagnostic against the exact preserved physical operator; no native GROOPS propagation or fits. Source, limits and every failure remain explicit.'")
(c/'stage_captured_tangent01.py').write_text(s)
