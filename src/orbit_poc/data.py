"""Estimator input contains observations and priors; never simulator truth."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import numpy as np

@dataclass
class Dataset:
    times: np.ndarray
    observations: dict
    prior_mean: np.ndarray
    prior_sigma: np.ndarray
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.times = np.asarray(self.times, dtype=float)
        self.prior_mean = np.asarray(self.prior_mean, dtype=float)
        self.prior_sigma = np.asarray(self.prior_sigma, dtype=float)
        self.observations = {k: np.asarray(v) for k, v in self.observations.items()}
        self.observations["node"] = self.observations["node"].astype(int)
        self.validate()

    def validate(self):
        n = len(self.times)
        o = self.observations
        m = len(o["node"])
        if n < 2 or np.any(np.diff(self.times) <= 0):
            raise ValueError("At least two strictly increasing node times are required")
        if np.max(np.diff(self.times)) > 60.000001:
            raise ValueError("Inference node spacing must be at most 60 seconds")
        if self.prior_mean.shape != (6,) or self.prior_sigma.shape != (6,) or np.any(self.prior_sigma <= 0):
            raise ValueError("Prior must contain six SI state components and positive standard deviations")
        for key, shape in {"station_pos": (m,3), "station_vel": (m,3), "y": (m,2)}.items():
            if o[key].shape != shape:
                raise ValueError(f"{key}: expected {shape}, got {o[key].shape}")
        if o["sigma"].shape not in {(2,), (m,2)} or np.any(o["sigma"] <= 0):
            raise ValueError("Measurement standard deviations must be positive, shape (2,) or (M,2)")
        if np.any(o["node"] < 0) or np.any(o["node"] >= n):
            raise ValueError("Measurement node index outside trajectory")
        if any(not np.all(np.isfinite(v)) for v in [self.times,self.prior_mean,self.prior_sigma,*o.values()]):
            raise ValueError("Dataset contains nonfinite values")
        return self

def save_dataset(dataset, path):
    path = Path(path)
    if path.suffix != ".npz":
        path = path / "dataset.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {"times": dataset.times, "prior_mean": dataset.prior_mean,
              "prior_sigma": dataset.prior_sigma, "metadata": np.array(json.dumps(dataset.metadata, default=str))}
    arrays.update({"obs_"+k:v for k,v in dataset.observations.items()})
    temp = path.with_suffix(".tmp.npz")
    np.savez_compressed(temp, **arrays)
    temp.replace(path)
    return path

def load_dataset(path):
    path = Path(path)
    if path.is_dir():
        path = path / "dataset.npz"
    with np.load(path, allow_pickle=False) as f:
        return Dataset(times=f["times"], observations={k[4:]:f[k] for k in f.files if k.startswith("obs_")},
                       prior_mean=f["prior_mean"], prior_sigma=f["prior_sigma"],
                       metadata=json.loads(str(f["metadata"])))

def subset_observations(dataset, mask):
    mask = np.asarray(mask, dtype=bool)
    obs = {k:(v[mask] if k != "sigma" or v.ndim == 2 else v.copy()) for k,v in dataset.observations.items()}
    return Dataset(dataset.times.copy(),obs,dataset.prior_mean.copy(),dataset.prior_sigma.copy(),dict(dataset.metadata))
