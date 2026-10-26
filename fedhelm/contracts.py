"""Shared, versioned wire contracts. FastAPI publishes these as OpenAPI."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Fault = Literal['healthy', 'service_down', 'config_error', 'pool_exhausted', 'thread_pool_exhausted', 'dependency_timeout', 'unknown']
Mode = Literal['lightweight', 'local', 'edge']
Action = Literal['none', 'restart_service', 'restore_config', 'reset_pool', 'reset_workers', 'restore_dependency']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    schema_version: Literal['1.0'] = '1.0'
    simulated: Literal[True] = True


class Observation(Contract):
    event_id: str
    node_id: str
    service_id: str
    healthy: bool
    error_rate: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0)
    pool_usage: float = Field(ge=0, le=1)
    logs: list[str]
    workload_backend: Literal['synthetic', 'process', 'kubernetes'] = 'synthetic'
    response_codes: list[int] = Field(default_factory=list)
    business_pid: int | None = None
    pod_name: str | None = None
    metrics: dict[str,float] = Field(default_factory=dict)
    spans: list[dict] = Field(default_factory=list)
    observed_at: float | None = None


class Resources(Contract):
    node_id: str
    tier: Literal['A', 'B', 'C']
    cpu_usage: float = Field(default=0.2, ge=0, le=1)
    memory_available_mb: int = Field(default=2048, ge=0)
    bandwidth_mbps: float = Field(default=50, gt=0)
    rtt_ms: float = Field(default=10, ge=0)
    edge_available: bool = True
    source: str = 'manual-policy'
    cpu_cores: int = 1
    energy_source: str = 'estimated, no power meter'
    bandwidth_source: str = 'configured prior'
    edge_queue: int = 0


class Diagnosis(Contract):
    event_id: str
    root_cause: Fault
    confidence: float = Field(ge=0, le=1)
    embedding: list[float] = Field(min_length=4, max_length=384)
    embedding_version: str = 'mock-features-v1'
    model_version: int = Field(ge=0)
    evidence: list[str]
    probabilities: dict[str,float] = Field(default_factory=dict)
    source: str = 'legacy'
    memory_conflict: bool = False


class Plan(Contract):
    event_id: str
    node_id: str
    service_id: str
    mode: Mode
    root_cause: Fault
    confidence: float = Field(ge=0, le=1)
    action: Action
    parameters: dict[str, str] = Field(default_factory=dict)
    reason: str


class InferenceRequest(Contract):
    observation: Observation
    diagnosis: Diagnosis
    retrieved_cases: list['Case'] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def matching_event(self):
        if self.observation.event_id != self.diagnosis.event_id:
            raise ValueError('observation and diagnosis event_id must match')
        return self


class Feedback(Contract):
    event_id: str
    success: bool
    samples: list[Observation]
    criterion: str


class Case(Contract):
    case_id: str
    source_node: str
    diagnosis: Diagnosis
    plan: Plan
    feedback: Feedback
    root_cause_confirmed: bool = False
    label_source: Literal['unconfirmed', 'synthetic_injector', 'testbed_injector','operator'] = 'unconfirmed'

    @model_validator(mode='after')
    def coherent_case(self):
        ids = {self.diagnosis.event_id, self.plan.event_id, self.feedback.event_id}
        if len(ids) != 1 or self.source_node != self.plan.node_id:
            raise ValueError('case event IDs and source node must match')
        if self.diagnosis.root_cause != self.plan.root_cause:
            raise ValueError('diagnosis and plan root cause must match')
        if self.root_cause_confirmed != (self.label_source in ('synthetic_injector', 'testbed_injector','operator')):
            raise ValueError('confirmation requires synthetic injector provenance')
        return self


class Search(Contract):
    embedding: list[float] = Field(min_length=4, max_length=384)
    embedding_version: str = 'mock-features-v1'
    top_k: int = Field(default=3, ge=1, le=20)


class Model(Contract):
    version: int = Field(default=0, ge=0)
    parameters: list[float] = Field(default_factory=lambda: [0.0] * 4, min_length=4, max_length=200000)
    adapter: Literal['mock-bias-v1','torch-mlp-v1','temporal-transformer-v2'] = 'mock-bias-v1'

    training_samples: int = Field(default=0,ge=0)

    @model_validator(mode='after')
    def parameter_shape(self):
        expected={'mock-bias-v1':4,'torch-mlp-v1':160,'temporal-transformer-v2':77542}[self.adapter]
        if len(self.parameters) != expected:
            raise ValueError('model parameter count does not match adapter')
        return self


class Update(Contract):
    node_id: str
    base_version: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    delta: list[float] = Field(min_length=4, max_length=200000)
    label_histogram: list[int] = Field(min_length=4, max_length=6)
    quality: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def valid_histogram(self):
        if any(n < 0 for n in self.label_histogram) or sum(self.label_histogram) != self.sample_count:
            raise ValueError('histogram must be nonnegative and sum to sample_count')
        return self


class RunRequest(Contract):
    event_id: str | None = Field(default=None,max_length=100)
    # Forced modes are explicitly for exercising adapters, not adaptive-policy claims.
    force_mode: Mode | None = None


class Injection(Contract):
    fault: Literal['healthy','service_down','config_error','pool_exhausted','thread_pool_exhausted','dependency_timeout']


InferenceRequest.model_rebuild()
