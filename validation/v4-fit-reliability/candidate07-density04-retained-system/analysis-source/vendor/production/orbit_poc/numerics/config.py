"""Strict configuration for the independent, fixed v3.1 numerical benchmark."""
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from orbit_poc.comparison.config import _construct

PROFILES = ("legacy_v3", "qr_lm_legacy_jacobian", "qr_lm_staged_jacobian")
METHODS = ("groops_pulses", "groops_log_drag_ou")
ORBITS = ("leo300", "leo500", "leo800", "eccentric")
FRESH_SEEDS = {"quiet": 510000, "disturbed": 510001}


def is_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class Artifact:
    path: str = ""
    sha256: str = ""

    def validate(self):
        if bool(self.path) != bool(self.sha256) or self.sha256 and not is_digest(self.sha256):
            raise ValueError("Artifact path and lowercase SHA256 must be supplied together")


@dataclass(frozen=True)
class Runtime:
    source_root: str = ""
    source_sha256: str = ""
    python: Artifact = field(default_factory=Artifact)
    native: Artifact = field(default_factory=Artifact)
    library_manifest: Artifact = field(default_factory=Artifact)
    supplemental_sources: Artifact = field(default_factory=Artifact)

    def validate(self):
        if bool(self.source_root) != bool(self.source_sha256) or self.source_sha256 and not is_digest(self.source_sha256):
            raise ValueError("Runtime source directory and SHA256 must be supplied together")
        for value in (self.python, self.native, self.library_manifest, self.supplemental_sources):
            value.validate()


@dataclass(frozen=True)
class Controls:
    maximum_accepted_iterations: int = 32
    maximum_trial_evaluations: int = 96
    wall_time_seconds: float = 7200.
    initial_damping: float = 1e-3
    minimum_gain_ratio: float = 1e-4
    maximum_position_change_m: float = 3e-5
    maximum_density_update: float = 1e-4
    maximum_pulse_update_m_s: float = 1e-8
    normalized_gradient_tolerance: float = 1e-8


@dataclass(frozen=True)
class Resources:
    # One timed attempt at a time; all profiles use the same CPU reservation.
    threads: int = 1
    reserve_bytes: int = 8 * 1024**3
    minimum_available_bytes: int = 16 * 1024**3
    maximum_process_tree_rss_bytes: int = 8 * 1024**3
    minimum_free_output_bytes: int = 64 * 1024**3
    reserved_output_bytes: int = 16 * 1024**3
    physical_backing_path: str = ""
    minimum_free_backing_bytes: int = 40 * 1024**3
    reserved_cpu_ids: tuple[int, ...] = ()
    protected_process_receipt: Artifact = field(default_factory=Artifact)


@dataclass(frozen=True)
class NumericsConfig:
    schema_version: int = 1
    name: str = "orbit-numerics-v3.1"
    output_dir: str = "runs/numerics-v3.1"
    preparation_dir: str = ""
    archive_dir: str = ""
    profiles: tuple[str, ...] = PROFILES
    legacy_runtime: Runtime = field(default_factory=Runtime)
    new_runtime: Runtime = field(default_factory=Runtime)
    comparison_config: Artifact = field(default_factory=Artifact)
    execution_context: Artifact = field(default_factory=Artifact)
    prepared_input_catalog: Artifact = field(default_factory=Artifact)
    prior_seed_protocols: tuple[Artifact, ...] = ()
    controls: Controls = field(default_factory=Controls)
    resources: Resources = field(default_factory=Resources)

    def to_dict(self):
        return asdict(self)

    def validate(self):
        if self.schema_version != 1 or self.profiles != PROFILES:
            raise ValueError("v3.1 requires exactly the three registered numerical profiles")
        if not self.name or not self.output_dir:
            raise ValueError("A name and separate output directory are required")
        for value in (self.legacy_runtime, self.new_runtime, self.comparison_config,
                      self.execution_context, self.prepared_input_catalog, *self.prior_seed_protocols):
            value.validate()
        self.resources.protected_process_receipt.validate()
        if self.controls != Controls():
            raise ValueError("The benchmark freezes 32 accepted iterations, 96 trials and a two-hour wall limit")
        r = self.resources
        if r.threads != 1 or r.reserve_bytes < 8 * 1024**3:
            raise ValueError("One BLAS/OpenMP thread and at least 8 GiB reserve are required")
        if min(r.minimum_available_bytes, r.maximum_process_tree_rss_bytes) <= 0:
            raise ValueError("Memory budgets must be positive")
        if r.minimum_available_bytes < r.reserve_bytes + r.maximum_process_tree_rss_bytes:
            raise ValueError("Available-memory threshold must include reserve and the whole worker budget")
        if r.reserved_output_bytes < 16 * 1024**3 or r.minimum_free_output_bytes < r.reserved_output_bytes + 32 * 1024**3:
            raise ValueError("Output storage requires at least 16 GiB reserve and 32 GiB additional working space")
        if r.minimum_free_backing_bytes < 40 * 1024**3:
            raise ValueError("Physical backing storage requires at least 40 GiB reserve")
        if len(set(r.reserved_cpu_ids)) != len(r.reserved_cpu_ids) or any(x < 0 for x in r.reserved_cpu_ids):
            raise ValueError("Reserved CPU IDs must be distinct nonnegative integers")
        return self


def config_from_dict(value):
    return _construct(NumericsConfig, value).validate()


def load_config(path):
    return config_from_dict(json.loads(Path(path).read_text()))
