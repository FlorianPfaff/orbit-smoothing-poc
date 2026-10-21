from pathlib import Path

def test_launcher_is_reviewed_lifecycle_with_explicit_separate_control_root():
 c=Path(__file__).parent;s=(c/'launch_segmented_validation01.py').read_text()
 s=s.replace('run_segmented_validation01.py','run_segmented_preparation01.py').replace('validation-launch','preparation-launch').replace('validation-driver','preparation-driver').replace('orbit-poc-v4-cli-validation-detached-launch-v1','orbit-poc-segmented-preparation-detached-launch-v1')
 s=s.replace("paths=execution['paths'];control=Path(paths['control'])", "paths=execution['paths'];control=Path(pins['control_root'])\n    if not control.is_absolute() or control.is_symlink() or str(control)!=json.loads(Path(pins['plan']['path']).read_text())['control_root']:raise RuntimeError('Preparation control root differs from pinned plan')")
 assert (c/'launch_segmented_preparation01.py').read_text()==s
