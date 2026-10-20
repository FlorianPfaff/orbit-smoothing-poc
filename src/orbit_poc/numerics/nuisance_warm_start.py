"""Accepted-point nuisance seeds; no factors, priors or ionosphere are reused."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import RLock

from orbit_poc.comparison.protocol import canonical_hash

PREFIX = "ORBIT_POC_NUISANCE_WARM"
MODES = {"receiver_clock_signal_float_v1", "receiver_clock_v1"}
DIGEST = re.compile(r"[0-9a-f]{64}")
ENV_LOCK = RLock()


def require(condition, message):
    if not condition:
        raise ValueError("Nuisance warm start: " + message)


@contextmanager
def without_inherited_warm_environment():
    """Serial worker boundary: inherited seed controls never reach a command."""
    with ENV_LOCK:
        saved = {k: v for k, v in os.environ.items() if k.startswith(PREFIX)}
        for key in saved:
            del os.environ[key]
        try:
            yield
        finally:
            for key in list(os.environ):
                if key.startswith(PREFIX):
                    del os.environ[key]
            os.environ.update(saved)


def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


@dataclass(frozen=True)
class FilePin:
    path: str
    sha256: str
    file_identity: tuple

    def record(self):
        return {"path": self.path, "sha256": self.sha256,
                "bytes": self.file_identity[3], "file_identity": list(self.file_identity)}


def pin_regular(path, root=None):
    """Hash one unchanged regular file; reject seed symlinks at every level."""
    path = Path(path).absolute()
    if root is not None:
        require(path.is_relative_to(root) and path.resolve(strict=True) == path,
                "seed path escapes its private directory or contains a symlink")
    require(not path.is_symlink(), "symlink is not a seed file")
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "seed is not a regular file")
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        require(identity(os.fstat(stream.fileno())) == identity(before), "file changed during open")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        require(identity(os.fstat(stream.fileno())) == identity(before), "file changed during hashing")
    require(identity(path.lstat()) == identity(before), "file changed after hashing")
    return FilePin(str(path), digest.hexdigest(), identity(before))


def check_pin(pin, root=None, *, rehash=True):
    path = Path(pin.path)
    require(not path.is_symlink() and path.resolve(strict=True) == path,
            "pinned file path changed or became a symlink")
    require(identity(path.lstat()) == pin.file_identity, "pinned file identity changed")
    if rehash:
        require(pin_regular(path, root) == pin, "pinned payload bytes changed")


def json_receipt(pin, root):
    require(pin.file_identity[3] <= 1024 * 1024, "companion receipt exceeds bounded metadata size")
    check_pin(pin, root)
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate companion JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("Nuisance warm start: nonfinite JSON " + value)
    fd = os.open(pin.path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        require(identity(os.fstat(stream.fileno())) == pin.file_identity, "companion changed during open")
        raw = stream.read()
        require(identity(os.fstat(stream.fileno())) == pin.file_identity and
                hashlib.sha256(raw).hexdigest() == pin.sha256, "companion bytes changed during read")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    check_pin(pin, root)
    return value


def state_hash(state):
    return canonical_hash({"initial": state.initial.tolist(), "force": state.force.tolist(),
                           "reference_orbit": str(state.reference_orbit)})


@dataclass(frozen=True)
class Seed:
    payload: FilePin
    companion: FilePin
    context: str
    mode: str
    chart: str
    cold_origin: str
    support: str
    state: str
    prefix: str
    generation: str

    def record(self):
        return {"payload": self.payload.record(), "companion": self.companion.record(),
                "context_sha256": self.context, "mode": self.mode,
                "chart_sha256": self.chart, "cold_origin_sha256": self.cold_origin,
                "support_hash": self.support, "source_state_sha256": self.state,
                "source_prefix": self.prefix, "source_generation": self.generation}


@dataclass(frozen=True)
class ProfilePlan:
    output: Path
    label: str
    donor: Seed | None


class WarmStartLifecycle:
    """A candidate export is inert until the optimizer calls accept(point)."""
    def __init__(self, job, prepared, binary, root, *, environment=None):
        env = os.environ if environment is None else environment
        flag = env.get(PREFIX + "_STARTS", "0")
        require(flag in ("0", "1"), "WARM_STARTS must be 0 or 1")
        self.enabled = flag == "1"
        self.mode = env.get(PREFIX + "_MODE", "receiver_clock_signal_float_v1") if self.enabled else None
        require(not self.enabled or self.mode in MODES, "unsupported warm-start mode")
        self.root = Path(root).resolve()
        self.donor = None
        self.pending = {}
        self.inputs = []
        self.context = None
        if not self.enabled:
            return
        inputs = [("native_binary", {"path": str(Path(binary).resolve()),
                   "sha256": job.get("expected_native_binary_sha256")})]
        inputs += [("estimation:" + str(i) + ":" + item["role"], item)
                   for i, item in enumerate(job["estimation_inputs"])]
        inputs += [("native:" + str(i) + ":" + item.get("role", "input"), item)
                   for i, item in enumerate(prepared.get("native_artifacts", []))]
        records = []
        for role, item in inputs:
            path = Path(item["path"]).resolve(strict=True)
            pin = pin_regular(path)
            expected = item.get("sha256")
            # v3 native jobs may omit the optional executable pin. Its actual
            # bytes are still part of the context; input artifacts require pins.
            require((role == "native_binary" and expected is None) or
                    expected == pin.sha256, "base input/native SHA mismatch: " + role)
            self.inputs.append((str(Path(item["path"]).absolute()), pin))
            records.append({"role": role, "sha256": pin.sha256, "bytes": pin.file_identity[3]})
        keys = ("method", "stage", "parameters", "numerical_controls", "numerics_profile",
                "segmented_profile", "force_model_hash", "measurement_model_hash",
                "preprocessing_hash", "mask_hash", "source_hash", "protocol_hash",
                "input_manifest_hash", "segmented_manifest_hash", "case", "split", "family_id")
        self.context = canonical_hash({"schema": "orbit-poc-nuisance-warm-context-v1",
            "job": {key: job[key] for key in keys if key in job}, "input_bytes": records,
            "mode": self.mode})
        self.job, self.prepared, self.job_keys = job, prepared, keys
        self.input_description_sha256 = self.description_hash()

    def description_hash(self):
        return canonical_hash({"job": {key: self.job[key] for key in self.job_keys if key in self.job},
            "estimation_inputs": self.job["estimation_inputs"], "prepared": self.prepared})

    def verify_inputs(self):
        require(self.description_hash() == self.input_description_sha256, "scientific job/preparation changed")
        for original, pin in self.inputs:
            require(Path(original).resolve(strict=True) == Path(pin.path), "base input link changed")
            check_pin(pin, rehash=False)

    def profile(self, folder, label, *, tighter=False, covariance=False):
        if not self.enabled:
            return {}, None
        self.verify_inputs()
        folder = Path(folder)
        require(folder.is_relative_to(self.root) and folder.resolve() == folder,
                "profile directory is not private")
        output = folder / "nuisance-warm-state.bin"
        require(not output.exists() and not output.is_symlink() and
                not Path(str(output) + ".json").exists() and not Path(str(output) + ".json").is_symlink(),
                "refusing to overwrite a seed or companion")
        is_trial = re.fullmatch(r"trial-[0-9]{3}", label) is not None and int(label[-3:]) > 0
        donor = self.donor if is_trial and not tighter and not covariance else None
        env = {PREFIX + "_STARTS": "1", PREFIX + "_MODE": self.mode,
               PREFIX + "_OUTPUT": str(output), PREFIX + "_CONTEXT_SHA256": self.context}
        if donor is not None:
            self.verify_seed(donor)
            env.update({PREFIX + "_INPUT": donor.payload.path, PREFIX + "_INPUT_SHA256": donor.payload.sha256})
        return env, ProfilePlan(output, label, donor)

    def verify_seed(self, seed):
        self.verify_inputs()
        require(seed.context == self.context and seed.mode == self.mode, "seed context/mode changed")
        check_pin(seed.payload, self.root)
        check_pin(seed.companion, self.root)

    def capture(self, point, plan, profile, diagnostics):
        """Validate an export after physical/support/factor checks, without installation."""
        if not self.enabled:
            return
        self.verify_inputs()
        require(plan is not None and plan.output.parent == Path(point.metadata["folder"]), "profile plan changed")
        if plan.donor is not None:
            self.verify_seed(plan.donor)
            require(point.support_hash == plan.donor.support, "warm target changed observation/parameter support")
        companion = pin_regular(str(plan.output) + ".json", self.root)
        value = json_receipt(companion, self.root)
        require(value.get("schema") == "orbit-poc-native-nuisance-warm-state-v1" and
                value.get("mode") == self.mode and value.get("context_sha256") == self.context,
                "companion schema/context/mode mismatch")
        require(value.get("source_prefix") == str(plan.output.parent / "qr") and
                value.get("source_generation") == point.metadata["factor_prefix"], "companion source generation mismatch")
        for key in ("chart_sha256", "cold_origin_sha256"):
            require(isinstance(value.get(key), str) and DIGEST.fullmatch(value[key]), "invalid " + key)
        imported = value.get("imported")
        expected = {"used": plan.donor is not None, "path": plan.donor.payload.path if plan.donor else "",
                    "sha256": plan.donor.payload.sha256 if plan.donor else ""}
        require(isinstance(imported, dict) and type(imported.get("used")) is bool and imported == expected,
                "companion import differs from controlled profile plan")
        if plan.donor is not None:
            require(value["chart_sha256"] == plan.donor.chart and value["cold_origin_sha256"] == plan.donor.cold_origin,
                    "native nuisance chart or cold origin changed")
        require(isinstance(value.get("invariants"), dict) and
                all(type(v) is bool for v in value["invariants"].values()) and
                value.get("invariants") == {"target_cold_ionosphere_unchanged": True,
                "target_clock_prior_anchors_unchanged": True}, "native target/prior invariant failed")
        counts = value.get("counts", {})
        require(type(counts.get("coordinates")) is int and counts["coordinates"] > 0, "empty/invalid exported coordinate count")
        limited = point.metadata.get("nuisance_floor_limited") is True
        strict = profile.get("nuisance_converged") is True and profile.get("nuisance_floor_limited") is False
        eligibility = value.get("eligibility", {})
        require(type(diagnostics.get("lambda")) in (int, float) and diagnostics["lambda"] == 0
                and diagnostics.get("rank_status") == "full",
                "export is not a fresh undamped full-rank factor")
        require(isinstance(eligibility, dict) and all(type(eligibility.get(k)) is bool for k in
                ("nuisance_converged", "nuisance_floor_limited", "fresh_undamped")) and
                eligibility == {"nuisance_converged": strict, "nuisance_floor_limited": limited,
                "fresh_undamped": True, "rank_status": "full"}, "export eligibility differs from native final status")
        seed = None
        if limited:
            require(not strict and value.get("export_status") == "ineligible" and value.get("payload_sha256") is None
                    and not plan.output.exists() and not plan.output.is_symlink(), "floor-limited point exported a seed")
        else:
            require(strict and value.get("export_status") == "exported", "strict point lacks eligible export")
            payload = pin_regular(plan.output, self.root)
            require(value.get("payload_sha256") == payload.sha256, "seed payload SHA differs from companion")
            seed = Seed(payload, companion, self.context, self.mode, value["chart_sha256"], value["cold_origin_sha256"],
                        point.support_hash, state_hash(point.state), value["source_prefix"], value["source_generation"])
        key = str(plan.output.parent)
        require(key not in self.pending, "evaluation already registered")
        self.pending[key] = (seed, limited, state_hash(point.state), point.support_hash, point.metadata["factor_prefix"], companion)
        point.metadata["nuisance_warm_start"] = {"enabled": True, "mode": self.mode,
            "context_sha256": self.context, "label": plan.label, "imported": expected,
            "candidate_export": seed.record() if seed else None, "floor_limited": limited,
            "scope": "Nuisance initialization only; ionosphere and priors remain cold; no covariance authorization"}

    def prepare_accept(self, point):
        if not self.enabled:
            return None
        self.verify_inputs()
        key = str(point.metadata["folder"])
        require(key in self.pending, "accepted point has no validated candidate export")
        seed, limited, state, support, generation, companion = self.pending[key]
        require((state, support, generation) == (state_hash(point.state), point.support_hash, point.metadata["factor_prefix"])
                and limited == (point.metadata.get("nuisance_floor_limited") is True), "accepted point identity changed")
        check_pin(companion, self.root)
        if seed is not None:
            self.verify_seed(seed)
        return seed  # None deliberately revokes a donor when a floor-limited point is accepted.

    def commit_accept(self, seed):
        if self.enabled:
            self.donor = seed
