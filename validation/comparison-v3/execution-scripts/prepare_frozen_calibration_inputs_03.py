"""Prepare calibration inputs only; no fitting, scoring, or acceptance approval."""
from pathlib import Path
import importlib.util
from orbit_poc.comparison.config import load_config
from orbit_poc.comparison.protocol import freeze_protocol,write_json,file_hash
p=Path('/home/florianpfaff/codex-runs/orbit-comparison-v3-20261013/project-test-candidate-03-complete/scripts/run_comparison_campaign.py')
spec=importlib.util.spec_from_file_location('maintained_campaign',p);driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
config=load_config('/home/florianpfaff/codex-runs/orbit-comparison-v3-20261013/production-config-03.json')
root=Path(config.output_dir);frozen=freeze_protocol(config,root)
resources=driver.launch_resources(24)
receipt={'scope':'Calibration input preparation only; no calibration fit, evaluation or acceptance approval','source_hash':frozen['source']['sha256'],'protocol_hash':frozen['protocol_hash'],'maintained_driver_sha256':file_hash(p),'invoker_sha256':file_hash(__file__),'resources':resources,'status':'preparing'}
write_json(root/'precalibration-input-launch.json',receipt)
try:
 receipt['result']=driver.prepare_calibration_inputs(config,root,frozen,'synthetic',resources['chosen_workers']);receipt['status']='prepared'
except Exception as error:
 receipt.update(status='failed',error=f'{type(error).__name__}: {error}');raise
finally:write_json(root/'precalibration-input-launch.json',receipt)
