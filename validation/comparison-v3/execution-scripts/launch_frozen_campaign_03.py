"""Launch the maintained frozen driver once, after actual acceptance evidence."""
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import os
import subprocess
import sys

from orbit_poc.comparison.config import load_config
from orbit_poc.comparison.gates import validate_gates
from orbit_poc.comparison.protocol import freeze_protocol, file_hash, write_json


def main():
    base = Path('/home/florianpfaff/codex-runs/orbit-comparison-v3-20261013')
    project = base/'project-test-candidate-03-complete'
    config_path = base/'production-config-03.json'
    config = load_config(config_path)
    root = Path(config.output_dir)
    frozen = freeze_protocol(config, root)
    if frozen['source']['sha256'] != '3b434b8c6d185187cc394795f901d082abd8fd2d38e6a7202feb0c52a105e33e':
        raise ValueError('Final runtime source changed')
    acceptance = validate_gates(root, frozen)
    driver = project/'scripts/run_comparison_campaign.py'
    argv = [sys.executable, str(driver), '--config', str(config_path),
            '--synthetic-workers', '24', '--flight-workers', '24']
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(project/'src'), PYTHONDONTWRITEBYTECODE='1',
        OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
        JAX_PLATFORMS='cpu', LD_LIBRARY_PATH=str(base/'native/lib'))
    # The child retains this open file description for its entire lifetime.
    # Closing it in the launcher does not release the child's advisory lock.
    with open(root/'campaign-driver-launch.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log_path = root/'campaign-driver.log'
        with open(log_path, 'ab', buffering=0) as log:
            child = subprocess.Popen(argv, cwd=project, env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, pass_fds=(lock.fileno(),))
        record = {'status':'launched', 'started_at':datetime.now(timezone.utc).isoformat(),
            'pid':child.pid, 'argv':argv, 'cwd':str(project), 'log':str(log_path),
            'launcher_sha256':file_hash(__file__), 'driver_sha256':file_hash(driver),
            'source_hash':frozen['source']['sha256'], 'protocol_hash':frozen['protocol_hash'],
            'acceptance_evidence_hash':acceptance['evidence_hash'],
            'config_sha256':file_hash(config_path),
            'scope':'Execution launch only; final completion is determined by campaign-driver.json and scientific reports'}
        write_json(root/'campaign-launch.json', record)
        print('Launched maintained campaign driver PID', child.pid)


if __name__ == '__main__':
    main()
