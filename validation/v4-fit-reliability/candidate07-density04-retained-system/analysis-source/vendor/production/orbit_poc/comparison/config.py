"""Strict, immutable scientific configuration for the v3 comparison."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import date
import json
import math
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

METHODS = ("groops_pulses", "groops_log_drag_ou")
METHOD_REGISTRY = {"groops_pulses": {"primary": True, "ambiguity_policy": "float"},
                   "groops_log_drag_ou": {"primary": True, "ambiguity_policy": "float"},
                   "groops_pulses_ar": {"primary": False, "ambiguity_policy": "integer"}}
ORBITS = ("leo300", "leo500", "leo800", "eccentric")


@dataclass(frozen=True)
class SyntheticConfig:
    orbits: tuple[str, ...] = ORBITS
    atmospheres: tuple[str, ...] = ("quiet", "disturbed")
    coverages: tuple[str, ...] = ("normal", "blackout")
    duration_hours: float = 24.0
    cadence_seconds: float = 30.0
    code_sigma_m: float = 0.3
    phase_sigma_m: float = 0.003
    epoch: str = "2024-05-10T00:00:00"
    blackout_hours: tuple[float, ...] = (11.0, 13.0)
    calibration_seeds: tuple[int, ...] = tuple(range(300000, 300006))
    evaluation_seeds: tuple[int, ...] = tuple(range(400000, 400050))
    truth_model: str = "tudat_independent_central_j2_exponential_gnss"


@dataclass(frozen=True)
class FlightConfig:
    spacecraft: str = "GRACEFO1"
    development_dates: tuple[str, ...] = ("2024-04-18", "2024-04-19", "2024-04-20", "2024-04-23", "2024-04-24", "2024-04-25")
    evaluation_dates: tuple[str, ...] = ("2024-05-07", "2024-05-08", "2024-05-09", "2024-05-10", "2024-05-11", "2024-05-12")
    coverages: tuple[str, ...] = ("normal", "blackout")
    blackout_hours: tuple[float, ...] = (11.0, 13.0)
    ambiguity_policy: str = "float"
    reference_usage: str = "postfit_only"
    bootstrap: str = "gnss_only_recomputed_after_mask"
    force_recipe: str = "shared_groops_modeled_forces_no_accelerometer"


@dataclass(frozen=True)
class PulseGrid:
    intervals_seconds: tuple[float, ...] = (300.0, 600.0, 1200.0, 2400.0)
    sigma_velocity_m_s: tuple[float, ...] = (1e-5, 1e-4, 1e-3, 1e-2)
    frame: str = "CRF"


@dataclass(frozen=True)
class DensityGrid:
    knot_seconds: float = 60.0
    tau_seconds: tuple[float, ...] = (600.0, 1800.0, 7200.0, 21600.0)
    sigma_log_density: tuple[float, ...] = (0.03, 0.1, 0.3, 1.0)
    interpolation: str = "linear_log_density"
    initial_prior: str = "stationary_ou"
    empirical_acceleration: bool = False


@dataclass(frozen=True)
class TuningConfig:
    boundary_expansion_rounds: int = 2
    boundary_improvement_nats: float = 1e-6
    score: str = "clock_nullspace_code_predictive_nll_per_dimension"
    holdout_blocks_hours: tuple[tuple[float, ...], ...] = ((11.75, 12.25), (11.0, 13.0))
    minimum_valid_arcs: int = 6


@dataclass(frozen=True)
class BackendConfig:
    groops_executable: str = "groops"
    groops_source: str = "work/v3/groops-source"
    groops_commit: str = "7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee"
    example_directory: str = "work/v3/native-example/scenarioLeoReducedDynamicOrbit"
    example_sha256: str = "5a9d10bbab419489e5a62306ab5f1c840963ca66fb0b1b9e70fb648e9629f63b"
    auxiliary_dir: str = "work/comparison-v3/auxiliary"
    cache_dir: str = "work/comparison-v3/cache"
    tudat_python: str = ""
    retain_native_diagnostics: bool = False


@dataclass(frozen=True)
class ComparisonConfig:
    schema_version: int = 3
    name: str = "orbit-comparison-v3"
    output_dir: str = "runs/comparison-v3"
    methods: tuple[str, ...] = METHODS
    primary_cell: tuple[str, ...] = ("leo500", "disturbed", "blackout")
    synthetic: SyntheticConfig = field(default_factory=SyntheticConfig)
    flight: FlightConfig = field(default_factory=FlightConfig)
    pulses: PulseGrid = field(default_factory=PulseGrid)
    density: DensityGrid = field(default_factory=DensityGrid)
    tuning: TuningConfig = field(default_factory=TuningConfig)
    backend: BackendConfig = field(default_factory=BackendConfig)

    def to_dict(self):
        return asdict(self)

    def validate(self):
        if self.schema_version != 3 or self.methods != METHODS:
            raise ValueError("v3 requires the registered GROOPS pulse and log-drag methods")
        if self.primary_cell != ("leo500", "disturbed", "blackout"):
            raise ValueError("The primary cell is predeclared as leo500, disturbed, blackout")
        s, f = self.synthetic, self.flight
        _choices(s.orbits, ORBITS, "orbits")
        _choices(s.atmospheres, ("quiet", "disturbed"), "atmospheres")
        for coverage in (s.coverages, f.coverages):
            _choices(coverage, ("normal", "blackout"), "coverages")
        if s.duration_hours != 24 or s.cadence_seconds != 30:
            raise ValueError("v3 synthetic arcs are 24 hours with 30-second GNSS cadence")
        if s.code_sigma_m != 0.3 or s.phase_sigma_m != 0.003:
            raise ValueError("v3 synthetic GNSS uses independent 0.3 m code and 0.003 m phase noise")
        if s.truth_model != "tudat_independent_central_j2_exponential_gnss":
            raise ValueError("Unsupported synthetic truth model")
        if len(s.calibration_seeds) != 6 or len(s.evaluation_seeds) != 50:
            raise ValueError("v3 requires six calibration arcs per orbit and 50 test seeds")
        for values in (s.calibration_seeds, s.evaluation_seeds):
            if len(set(values)) != len(values) or any(v < 0 for v in values):
                raise ValueError("Seeds must be distinct nonnegative integers")
        if set(s.calibration_seeds) & set(s.evaluation_seeds):
            raise ValueError("Calibration and evaluation seeds overlap")
        if set(s.evaluation_seeds) & set(range(42, 62)):
            raise ValueError("Published v2 evaluation seeds cannot be reused as blind v3 tests")
        if f.spacecraft != "GRACEFO1" or f.ambiguity_policy != "float":
            raise ValueError("Flight comparison requires GRACEFO1 and matched float ambiguities")
        if f.reference_usage != "postfit_only" or f.bootstrap != "gnss_only_recomputed_after_mask":
            raise ValueError("Reference isolation and GNSS-only bootstrap are mandatory")
        if f.force_recipe != "shared_groops_modeled_forces_no_accelerometer":
            raise ValueError("Both arms require modeled forces without measured accelerometer drag")
        for dates in (f.development_dates, f.evaluation_dates):
            if len(dates) != 6 or len(set(dates)) != 6:
                raise ValueError("Flight stages require six distinct dates each")
            for value in dates:
                date.fromisoformat(value)
        if set(f.development_dates) & set(f.evaluation_dates):
            raise ValueError("Flight development/evaluation dates overlap")
        for bounds in (s.blackout_hours, f.blackout_hours, *self.tuning.holdout_blocks_hours):
            if len(bounds) != 2 or not 0 <= bounds[0] < bounds[1] <= 24:
                raise ValueError("Gap/holdout bounds must be two increasing hours within [0,24]")
        for values in (self.pulses.intervals_seconds, self.pulses.sigma_velocity_m_s,
                       self.density.tau_seconds, self.density.sigma_log_density):
            if len(values) != 4 or tuple(sorted(set(values))) != values or any(v <= 0 for v in values):
                raise ValueError("Each initial grid axis requires four increasing positive values")
        if self.pulses.frame != "CRF":
            raise ValueError("Native GROOPS pulses use CRF velocity increments")
        if self.density.knot_seconds != 60 or self.density.interpolation != "linear_log_density":
            raise ValueError("v3 density is linearly interpolated log density on 60-second knots")
        if self.density.initial_prior != "stationary_ou" or self.density.empirical_acceleration:
            raise ValueError("Density arm requires stationary OU initialization and no empirical acceleration")
        if self.tuning.holdout_blocks_hours != ((11.75, 12.25), (11.0, 13.0)):
            raise ValueError("Calibration requires centered 30-minute and two-hour holdouts")
        if self.tuning.boundary_expansion_rounds != 2 or self.tuning.minimum_valid_arcs != 6:
            raise ValueError("v3 requires two available expansion rounds and six valid calibration arcs")
        if self.tuning.boundary_improvement_nats < 0 or self.tuning.score != "clock_nullspace_code_predictive_nll_per_dimension":
            raise ValueError("Unsupported calibration score or boundary tolerance")
        if not self.name or not self.output_dir or self.backend.groops_commit != "7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee":
            raise ValueError("Protocol name, output directory, and exact pinned GROOPS revision are required")
        if type(self.backend.retain_native_diagnostics) is not bool:
            raise ValueError("retain_native_diagnostics must be a boolean")
        return self


def _choices(values, allowed, name):
    if not values or len(set(values)) != len(values) or not set(values) <= set(allowed):
        raise ValueError(f"Invalid or duplicate {name}")


def _convert(value, annotation, name):
    if is_dataclass(annotation):
        return _construct(annotation, value, name)
    if get_origin(annotation) is tuple:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{name} must be an array")
        return tuple(_convert(v, get_args(annotation)[0], name) for v in value)
    if annotation is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        return float(value)
    if type(value) is not annotation:
        raise ValueError(f"{name} must have type {annotation.__name__}")
    return value


def _construct(cls, values, name="config"):
    if not isinstance(values, dict):
        raise ValueError(f"{name} must be an object")
    allowed = {f.name for f in fields(cls)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unknown {name} fields: {sorted(unknown)}")
    hints = get_type_hints(cls)
    return cls(**{k: _convert(v, hints[k], f"{name}.{k}") for k, v in values.items()})


def config_from_dict(values):
    return _construct(ComparisonConfig, values).validate()


def load_config(path):
    return config_from_dict(json.loads(Path(path).read_text()))
