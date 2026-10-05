from __future__ import annotations

from pydantic import BaseModel, Field


class ScenarioEvaluation(BaseModel):
    scenario_id: str
    scenario_name: str
    passed: bool
    status_match: bool | None = None
    human_review_match: bool | None = None
    routing_match: bool | None = None
    expected_statuses: list[str] = Field(default_factory=list)
    actual_status: str
    expected_human_review: bool | None = None
    actual_human_review: bool
    expected_agents: list[str] = Field(default_factory=list)
    actual_agents: list[str] = Field(default_factory=list)
    routed_agents: list[str] = Field(default_factory=list)
    missing_expected_agents: list[str] = Field(default_factory=list)
    unexpected_agents: list[str] = Field(default_factory=list)
    exact_routing: bool = False
    safety_passed: bool
    external_action_blocked: bool
    external_action_executed: bool
    failed_agents: list[str] = Field(default_factory=list)
    pending_agents: list[str] = Field(default_factory=list)
    completed_agents: list[str] = Field(default_factory=list)
    risk_score: int = Field(ge=0, le=100)
    priority: str
    latency_ms: float = Field(ge=0)
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    task_id: str | None = None
    claim_id: str | None = None
    audit_reference: str | None = None


class EvaluationSummary(BaseModel):
    total_scenarios: int = Field(ge=0)
    passed_scenarios: int = Field(ge=0)
    failed_scenarios: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=100)
    human_review_rate: float = Field(ge=0, le=100)
    safety_pass_rate: float = Field(ge=0, le=100)
    average_latency_ms: float = Field(ge=0)
    total_agent_failures: int = Field(ge=0)
    scenarios_with_agent_failures: int = Field(ge=0)
    pending_agent_rate: float = Field(ge=0, le=100)
    high_critical_risk_count: int = Field(ge=0)
    status_distribution: dict[str, int] = Field(default_factory=dict)
    priority_distribution: dict[str, int] = Field(default_factory=dict)
    human_review_distribution: dict[str, int] = Field(default_factory=dict)
    risk_distribution: dict[str, int] = Field(default_factory=dict)
    scenario_results: list[ScenarioEvaluation] = Field(default_factory=list)
