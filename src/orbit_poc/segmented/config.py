"""Independent strict configuration for the fixed 68-attempt v4 benchmark."""
from __future__ import annotations
from dataclasses import asdict,dataclass,field,fields,is_dataclass
import json,math
from pathlib import Path
from typing import get_args,get_origin,get_type_hints

PROFILES=("dense_corrected","segmented_1h","segmented_4h")
METHODS=("groops_pulses","groops_log_drag_ou")
FRESH_SEEDS={"leo500":610000,"eccentric":610001}

def is_digest(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)

@dataclass(frozen=True)
class Artifact:
    path:str=""
    sha256:str=""
    def validate(self):
        if bool(self.path)!=bool(self.sha256) or self.sha256 and not is_digest(self.sha256):
            raise ValueError('Artifact path and lowercase SHA256 must be supplied together')

@dataclass(frozen=True)
class Runtime:
    source_root:str=""
    source_sha256:str=""
    python:Artifact=field(default_factory=Artifact)
    native:Artifact=field(default_factory=Artifact)
    build_manifest:Artifact=field(default_factory=Artifact)
    library_manifest:Artifact=field(default_factory=Artifact)
    segmented_solver:Artifact=field(default_factory=Artifact)
    def validate(self):
        if bool(self.source_root)!=bool(self.source_sha256) or self.source_sha256 and not is_digest(self.source_sha256):
            raise ValueError('Runtime source directory and digest must be supplied together')
        for v in (self.python,self.native,self.build_manifest,self.library_manifest,self.segmented_solver):v.validate()

@dataclass(frozen=True)
class Controls:
    maximum_accepted_iterations:int=32
    maximum_trial_evaluations:int=96
    wall_time_seconds:float=7200.
    initial_damping:float=1e-3
    minimum_gain_ratio:float=1e-4
    maximum_position_change_m:float=3e-5
    maximum_density_update:float=1e-4
    maximum_pulse_update_m_s:float=1e-8
    normalized_gradient_tolerance:float=1e-8

@dataclass(frozen=True)
class Resources:
    threads:int=1
    maximum_process_tree_rss_bytes:int=8*1024**3
    reserve_bytes:int=8*1024**3
    reserved_cpu_ids:tuple[int,...]=()
    minimum_free_output_bytes:int=32*1024**3
    admission:Artifact=field(default_factory=Artifact)

@dataclass(frozen=True)
class Preparation:
    cache_dir:str=""
    auxiliary_dir:str=""
    example_directory:str=""
    tudat_python:str=""
    tudat_python_sha256:str=""
    interpolation_margin_seconds:float=3600.
    generate_missing:bool=False

@dataclass(frozen=True)
class SegmentedConfig:
    schema_version:int=1
    name:str="orbit-segmented-v4"
    output_dir:str="runs/segmented-v4"
    profiles:tuple[str,...]=PROFILES
    dense_runtime:Runtime=field(default_factory=Runtime)
    segmented_runtime:Runtime=field(default_factory=Runtime)
    validation_inputs:Artifact=field(default_factory=Artifact)
    flight_input_catalog:Artifact=field(default_factory=Artifact)
    corrected_reference:Artifact=field(default_factory=Artifact)
    prepared_input_catalog:Artifact=field(default_factory=Artifact)
    prior_seed_protocols:tuple[Artifact,...]=()
    release_evidence:Artifact=field(default_factory=Artifact)
    original150_report:Artifact=field(default_factory=Artifact)
    original150_manifest:Artifact=field(default_factory=Artifact)
    original150_plan:Artifact=field(default_factory=Artifact)
    controls:Controls=field(default_factory=Controls)
    resources:Resources=field(default_factory=Resources)
    preparation:Preparation=field(default_factory=Preparation)
    def to_dict(self):return asdict(self)
    def validate(self):
        if self.schema_version!=1 or self.profiles!=PROFILES or not self.name or not self.output_dir:
            raise ValueError('v4 requires its separate name/output and exact three registered profiles')
        if self.controls!=Controls():raise ValueError('The existing v3.1 numerical controls and thresholds are fixed')
        for v in (self.dense_runtime,self.segmented_runtime,self.validation_inputs,self.flight_input_catalog,self.corrected_reference,self.prepared_input_catalog,self.release_evidence,self.original150_report,self.original150_manifest,self.original150_plan,*self.prior_seed_protocols):v.validate()
        self.resources.admission.validate();r=self.resources
        if r.threads!=1 or r.maximum_process_tree_rss_bytes!=8*1024**3 or r.reserve_bytes<8*1024**3:
            raise ValueError('Use one thread, an8GiB whole-process limit and at least8GiB reserve')
        if r.minimum_free_output_bytes<32*1024**3 or len(set(r.reserved_cpu_ids))!=len(r.reserved_cpu_ids) or any(x<0 for x in r.reserved_cpu_ids):
            raise ValueError('Invalid reserved CPU or output storage configuration')
        Artifact(self.preparation.tudat_python,self.preparation.tudat_python_sha256).validate()
        if self.preparation.interpolation_margin_seconds<3600 or not math.isfinite(self.preparation.interpolation_margin_seconds):
            raise ValueError('All daily transmitter products require at least one hour of interpolation margin')
        return self

def _convert(kind,value,name):
    if is_dataclass(kind):return _construct(kind,value,name)
    if get_origin(kind) is tuple:
        if not isinstance(value,list):raise ValueError(name+' must be a JSON array')
        return tuple(_convert(get_args(kind)[0],x,name) for x in value)
    if kind is float:
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError(name+' must be finite numeric')
        return float(value)
    if kind in (int,str,bool) and type(value) is not kind:raise ValueError(name+' has an invalid type')
    return value

def _construct(cls,value,name='config'):
    if not isinstance(value,dict):raise ValueError(name+' must be an object')
    known={f.name for f in fields(cls)};unknown=set(value)-known
    if unknown:raise ValueError('Unknown '+name+' options: '+', '.join(sorted(unknown)))
    types=get_type_hints(cls)
    return cls(**{k:_convert(types[k],v,name+'.'+k) for k,v in value.items()})

def config_from_dict(value):return _construct(SegmentedConfig,value).validate()
def load_config(path):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('Duplicate configuration key: '+k)
            d[k]=v
        return d
    return config_from_dict(json.loads(Path(path).read_text(),object_pairs_hook=pairs))
