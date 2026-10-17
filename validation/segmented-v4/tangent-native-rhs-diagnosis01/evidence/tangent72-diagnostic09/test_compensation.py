from pathlib import Path
import subprocess
HERE=Path(__file__).parent

def test_analytic_cancellation_and_velocity_carry():
    r=subprocess.run([str(HERE/'probe'),'--compensation'],capture_output=True,text=True)
    assert r.returncode==0 and not r.stderr
    assert r.stdout=='compensated cancellation and coupled chronological integral passed\n'
