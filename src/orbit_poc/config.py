"""Explicit units and immutable inference-model configuration."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

MU = 3.986004418e14
EARTH_RADIUS = 6378137.0
J2 = 1.08262668e-3
OMEGA = 7.2921150e-5
MASS = 100.0
AREA = 1.0
CD = 2.2
RHO_500 = 5e-13
SCALE_HEIGHT = 60000.0

@dataclass(frozen=True)
class ModelSpec:
    model: str = "density"
    tau: float = 7200.0
    sigma: float = 0.3
    q_acc: float = 1e-14
    accel_sigma: float = 1e-7
    substep: float = 2.5

    def __post_init__(self):
        if self.model not in {"white", "colored", "density"}:
            raise ValueError(f"Unknown model: {self.model}")
        if self.tau <= 0 or self.sigma <= 0 or self.accel_sigma <= 0:
            raise ValueError("OU correlation time and stationary standard deviations must be positive")
        if self.q_acc <= 0 or not 0 < self.substep <= 60:
            raise ValueError("q_acc must be positive; substep must lie in (0,60] seconds")

    @property
    def dimension(self):
        return {"white": 6, "colored": 9, "density": 7}[self.model]

    def to_dict(self):
        return asdict(self)

def config_hash(config):
    return sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

def load_config(path):
    path = Path(path)
    if path.suffix in {".yaml", ".yml"}:
        import yaml
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())
