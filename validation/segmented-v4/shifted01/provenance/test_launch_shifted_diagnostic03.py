from pathlib import Path

def test_only_reviewed_launcher_metadata_changes():
 c=Path(__file__).parent;old=(c/'launch_segmented_validation01.py').read_text();new=(c/'launch_shifted_diagnostic03.py').read_text()
 assert new==old.replace('run_segmented_validation01.py','run_shifted_diagnostic03.py').replace('validation-launch','shifted-launch').replace('validation-driver','shifted-driver').replace('orbit-poc-v4-cli-validation-detached-launch-v1','orbit-poc-shifted-diagnostic-detached-launch-v1')
