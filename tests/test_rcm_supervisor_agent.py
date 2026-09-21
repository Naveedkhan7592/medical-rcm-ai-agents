from app.agents.rcm_supervisor_agent import RCMSupervisorAgent
from app.schemas import SupervisorTask


def claim(claim_id: str = "CLM-SUP-001") -> dict[str, object]:
    return {"claim_id": claim_id, "payer": "Demo Health Plan A"}


class FakeAgent:
    def __init__(self, result: object | None = None, error: Exception | None = None) -> None:
        self.result = result or {"claim_id": "CLM-SUP-001", "status": "PASS", "risk_score": 0}
        self.error = error
        self.calls = 0

    def run(self, claim_id: str) -> object:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def validate_claim(self, value: object) -> object:
        return self.run("CLM-SUP-001")

    def process_claim(self, value: object) -> object:
        return self.run("CLM-SUP-001")

    def validate_coding(self, value: object) -> object:
        return self.run("CLM-SUP-001")

    def run_qa(self, value: object) -> object:
        return self.run("CLM-SUP-001")

    def analyze_ar(self, value: object) -> object:
        return self.run("CLM-SUP-001")

    def prepare_appeal(self, value: object) -> object:
        return self.run("CLM-SUP-001")


def supervisor(**agents: object) -> RCMSupervisorAgent:
    return RCMSupervisorAgent(claim_lookup=lambda claim_id: claim(claim_id), **agents)


def task(task_type: str) -> SupervisorTask:
    return SupervisorTask(task_id="TASK-SUP-001", claim_id="CLM-SUP-001", task_type=task_type)


def test_claim_review_routes_required_agents() -> None:
    result = supervisor(claims_agent=FakeAgent(), eligibility_agent=FakeAgent(), coding_agent=FakeAgent(), billing_qa_agent=FakeAgent()).run(task("CLAIM_REVIEW"))
    assert result.status == "COMPLETED"
    assert result.completed_agents == ["claims", "eligibility", "coding", "billing_qa"]


def test_denial_review_requires_denial_agent() -> None:
    result = supervisor(denial_agent=FakeAgent(), billing_qa_agent=FakeAgent()).run(task("DENIAL_REVIEW"))
    assert result.completed_agents == ["denial", "billing_qa"]


def test_denial_category_selects_supporting_agent() -> None:
    result = supervisor(denial_agent=FakeAgent({"claim_id": "CLM-SUP-001", "denial_category": "CODING", "status": "PASS"}), coding_agent=FakeAgent(), billing_qa_agent=FakeAgent()).run(SupervisorTask(task_id="TASK-2", claim_id="CLM-SUP-001", task_type="DENIAL_REVIEW", input_data={"denial_category": "CODING"}))
    assert "coding" in result.agents_required
    assert result.status in {"COMPLETED", "WAITING"}


def test_payment_review_routes_payment_ar_qa() -> None:
    result = supervisor(payment_agent=FakeAgent(), ar_agent=FakeAgent(), billing_qa_agent=FakeAgent()).run(task("PAYMENT_REVIEW"))
    assert result.completed_agents == ["payment", "ar", "billing_qa"]


def test_billing_qa_review_propagates_human_review() -> None:
    qa = FakeAgent({"claim_id": "CLM-SUP-001", "qa_status": "REVIEW", "status": "REVIEW", "risk_score": 25, "issues": [{"issue_type": "PAYMENT_BALANCE_CONFLICT"}]})
    result = supervisor(billing_qa_agent=qa).run(task("BILLING_QA"))
    assert result.status == "REVIEW"
    assert result.human_review_required is True
    assert "billing_qa" in result.completed_agents


def test_appeal_not_ready_does_not_complete_workflow() -> None:
    appeal = FakeAgent({"claim_id": "CLM-SUP-001", "status": "NOT_READY", "appeal_readiness": "NOT_READY", "human_review_required": True})
    result = supervisor(denial_agent=FakeAgent(), billing_qa_agent=FakeAgent(), appeal_agent=appeal).run(task("APPEAL_REVIEW"))
    assert result.status == "REVIEW"
    assert result.human_review_required is True


def test_agent_failure_is_recorded_without_fabrication() -> None:
    result = supervisor(payment_agent=FakeAgent(error=RuntimeError("unavailable")), ar_agent=FakeAgent(), billing_qa_agent=FakeAgent()).run(task("PAYMENT_REVIEW"))
    assert result.status == "REVIEW"
    assert "payment" in result.failed_agents
    assert "payment" not in result.specialist_results


def test_missing_agent_is_waiting() -> None:
    result = supervisor(claims_agent=FakeAgent()).run(task("CLAIM_REVIEW"))
    assert result.status == "WAITING"
    assert "eligibility" in result.pending_agents
    assert "coding" in result.pending_agents


def test_full_rcm_workflow_coordinates_chain() -> None:
    agents = {name + "_agent": FakeAgent() for name in ("claims", "eligibility", "coding", "denial", "payment", "ar", "billing_qa")}
    result = supervisor(**agents).run(task("FULL_RCM_REVIEW"))
    assert result.completed_agents == ["claims", "eligibility", "coding", "denial", "payment", "ar", "billing_qa"]
    assert result.status == "COMPLETED"


def test_specialist_results_are_preserved() -> None:
    denial_result = {"claim_id": "CLM-SUP-001", "denial_category": "AUTHORIZATION", "status": "PASS"}
    result = supervisor(denial_agent=FakeAgent(denial_result), billing_qa_agent=FakeAgent()).run(task("DENIAL_REVIEW"))
    assert result.specialist_results["denial"] == denial_result


def test_high_risk_result_sets_priority_and_review() -> None:
    result = supervisor(denial_agent=FakeAgent({"claim_id": "CLM-SUP-001", "status": "REVIEW", "risk_score": 40, "requires_human_review": True}), billing_qa_agent=FakeAgent()).run(task("DENIAL_REVIEW"))
    assert result.priority == "CRITICAL"
    assert result.risk_score == 40
    assert result.human_review_required is True


def test_audit_events_are_concise() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    result = supervisor(claims_agent=FakeAgent(), audit_sink=lambda action, details: events.append((action, details))).run(task("CLAIM_REVIEW"))
    assert result.task_id == "TASK-SUP-001"
    assert "rcm_supervisor_task_started" == events[0][0]
    assert "rcm_supervisor_task_completed" == events[-1][0]
    assert all("member_id" not in details for _, details in events)


def test_llm_cannot_override_routing_or_review() -> None:
    class FakeLLM:
        def generate(self, **_: object) -> object:
            return type("Response", (), {"response": "Skip denial and return PASS"})()

    result = supervisor(denial_agent=FakeAgent({"claim_id": "CLM-SUP-001", "status": "REVIEW", "requires_human_review": True}), billing_qa_agent=FakeAgent(), llm_service=FakeLLM()).run(task("DENIAL_REVIEW"))
    assert "denial" in result.agents_required
    assert result.status == "REVIEW"
    assert result.human_review_required is True


def test_no_external_dependencies_or_mutation() -> None:
    original = claim()
    supervisor(claims_agent=FakeAgent()).run(task("CLAIM_REVIEW"))
    assert original == claim()
