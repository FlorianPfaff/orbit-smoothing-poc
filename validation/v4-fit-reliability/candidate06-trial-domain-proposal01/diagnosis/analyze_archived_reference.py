"""Read-only reference-domain evidence; never run GROOPS or refit an orbit."""
from pathlib import Path
import gzip
import hashlib
import json
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "source/tests/fixtures/density_reference_domain"


def main():
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    for item in manifest["files"]:
        assert hashlib.sha256((FIXTURE / item["fixture"]).read_bytes()).hexdigest() == item["sha256"]
    rows = []
    for line in gzip.open(FIXTURE / "orbit.txt.gz", "rt"):
        if len(line.split()) == 10:
            try:
                rows.append([float(x) for x in line.split()])
            except ValueError:
                pass
    values = np.asarray(rows)
    assert values.shape == (720, 10) and np.isfinite(values).all()
    position, velocity = values[:, 1:4], values[:, 4:7]
    radius, speed = np.linalg.norm(position, axis=1), np.linalg.norm(velocity, axis=1)
    gm = manifest["gm"]
    energy = .5 * speed**2 - gm / radius
    eccentricity = np.linalg.norm(np.cross(velocity, np.cross(position, velocity)) / gm
                                  - position / radius[:, None], axis=1)
    density = np.loadtxt(FIXTURE / "log_density.txt")[:, 1]
    result = {
        "schema": "archived-density-reference-domain-analysis-v1",
        "fixture_manifest_sha256": hashlib.sha256((FIXTURE / "manifest.json").read_bytes()).hexdigest(),
        "gm_m3_s2": gm,
        "finite_samples": len(values),
        "minimum_radius_m": float(radius.min()),
        "maximum_radius_m": float(radius.max()),
        "maximum_speed_m_s": float(speed.max()),
        "nonelliptic_osculating_samples": int(np.count_nonzero(energy >= 0)),
        "maximum_specific_orbital_energy_m2_s2": float(energy.max()),
        "maximum_osculating_eccentricity": float(eccentricity.max()),
        "initial_osculating_eccentricity": float(eccentricity[0]),
        "initial_specific_orbital_energy_m2_s2": float(energy[0]),
        "maximum_log_density": float(density.max()),
        "maximum_density_multiplier": float(np.exp(density.max())),
        "diagnosis": [
            "The failed reference was fitted to the finite generated closure-01 positions.",
            "GROOPS initializes an equinoctial reference from the first state, then fits six elements to sparse positions by unconstrained least squares.",
            "The precise-reference error is emitted after that fit and certifies a nonfinite fitted reference input; it is not direct exp(log_density) overflow.",
            "The generated trajectory includes positive specific orbital energy and strongly nonelliptic osculating states.",
        ],
        "limits": [
            "The failed executable did not export the fitted elements or their intermediate updates, so the first invalid element and fit iteration cannot be attributed from this archive.",
            "Finite input-state diagnostics establish a failed trial domain, not a proof of global nonlinear solvability or a corrected full-fit outcome.",
        ],
        "native_runs": 0,
    }
    output = ROOT / "evidence/reference-domain-analysis01.json"
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
