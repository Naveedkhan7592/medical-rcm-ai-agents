from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.schemas import (
    AppealReadiness,
    BillingQAStatus,
    SupervisorAgentSummary,
    SupervisorPriority,
    SupervisorResult,
    SupervisorStatus,
    SupervisorTask,
    SupervisorTaskType,
)
from app.services.llm_service import LLMService, LLMServiceError


Lookup = Callable[[str], Any | None]
AuditSink = Callable[[str, dict[str, Any]], None]
SCORES = {"CRITICAL": 40, "HIGH": 25, "MEDIUM": 15, "LOW": 5}

ROUTES = {
    SupervisorTaskType.CLAIM_REVIEW: ["claims", "eligibility", "coding", "billing_qa"],
    SupervisorTaskType.DENIAL_REVIEW: ["denial", "billing_qa"],
    SupervisorTaskType.PAYMENT_REVIEW: ["payment", "ar", "billing_qa"],
    SupervisorTaskType.AR_REVIEW: ["payment", "ar", "billing_qa"],
    SupervisorTaskType.BILLING_QA: ["billing_qa"],
    SupervisorTaskType.APPEAL_REVIEW: ["denial", "billing_qa", "appeal"],
    SupervisorTaskType.FULL_RCM_REVIEW: ["claims", "eligibility", "coding", "denial", "payment", "ar", "billing_qa"],
}


def _value(item: Mapping[str, Any] | Any | None, name: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


class RCMSupervisorAgent:
    """Deterministically route and aggregate specialist RCM results."""

    def __init__(
        self,
        *,
        claim_lookup: Lookup | None = None,
        patient_lookup: Lookup | None = None,
        claim_history_lookup: Lookup | None = None,
        payer_policy_lookup: Lookup | None = None,
        eligibility_agent: Any | None = None,
        claims_agent: Any | None = None,
        coding_agent: Any | None = None,
        denial_agent: Any | None = None,
        payment_agent: Any | None = None,
        ar_agent: Any | None = None,
        billing_qa_agent: Any | None = None,
        appeal_agent: Any | None = None,
        rules_engine: Any | None = None,
        llm_service: LLMService | Any | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.claim_lookup = claim_lookup
        self.patient_lookup = patient_lookup
        self.claim_history_lookup = claim_history_lookup
        self.payer_policy_lookup = payer_policy_lookup
        self.agents = {
            "eligibility": eligibility_agent,
            "claims": claims_agent,
            "coding": coding_agent,
            "denial": denial_agent,
            "payment": payment_agent,
            "ar": ar_agent,
            "billing_qa": billing_qa_agent,
            "appeal": appeal_agent,
        }
        self.rules_engine = rules_engine
        self.llm_service = llm_service
        self.audit_sink = audit_sink

    def run(self, task: SupervisorTask | Mapping[str, Any]) -> SupervisorResult:
        task_model = task if isinstance(task, SupervisorTask) else SupervisorTask.model_validate(task)
        self._audit("rcm_supervisor_task_started", task_model, "started")
        claim = self.claim_lookup(task_model.claim_id) if self.claim_lookup else None
        self._audit("rcm_supervisor_claim_loaded", task_model, "found" if claim else "missing")
        self._audit("rcm_supervisor_task_classified", task_model, task_model.task_type.value)
        required = list(ROUTES[task_model.task_type])
        required = self._refine_route(task_model, required)
        self._audit("rcm_supervisor_agents_selected", task_model, ",".join(required))

        results: dict[str, Any] = {}
        summaries: list[SupervisorAgentSummary] = []
        failed: list[str] = []
        pending: list[str] = []
        missing: list[str] = []
        reasons: list[str] = []
        for agent_name in required:
            agent = self.agents.get(agent_name)
            if agent is None:
                pending.append(agent_name)
                missing.append(f"{agent_name} agent result")
                summaries.append(SupervisorAgentSummary(agent_name=agent_name, status="PENDING", result_available=False))
                self._audit("rcm_supervisor_waiting_for_input", task_model, agent_name)
                continue
            self._audit("rcm_supervisor_agent_started", task_model, agent_name)
            try:
                result = self._invoke(agent_name, agent, task_model.claim_id, claim)
                if result is None:
                    pending.append(agent_name)
                    missing.append(f"{agent_name} result")
                    summaries.append(SupervisorAgentSummary(agent_name=agent_name, status="MISSING", result_available=False))
                else:
                    results[agent_name] = result
                    summaries.append(SupervisorAgentSummary(agent_name=agent_name, status="COMPLETED", result_available=True))
                    self._audit("rcm_supervisor_agent_completed", task_model, agent_name)
            except Exception as exc:
                failed.append(agent_name)
                summaries.append(SupervisorAgentSummary(agent_name=agent_name, status="FAILED", result_available=False, error=type(exc).__name__))
                reasons.append(f"{agent_name} failed without a fabricated result")
                self._audit("rcm_supervisor_agent_failed", task_model, agent_name)

        if task_model.task_type in {SupervisorTaskType.DENIAL_REVIEW, SupervisorTaskType.APPEAL_REVIEW, SupervisorTaskType.FULL_RCM_REVIEW}:
            self._route_based_on_denial(results, required, task_model, pending)
        self._audit("rcm_supervisor_results_aggregated", task_model, str(len(results)))
        risk_score, priority, human_review = self._aggregate_risk(results, failed, pending)
        self._audit("rcm_supervisor_risk_evaluated", task_model, str(risk_score))
        status, stage, next_action = self._workflow_state(task_model, required, results, failed, pending, human_review)
        if human_review:
            self._audit("rcm_supervisor_human_review_required", task_model, status.value)
        self._audit("rcm_supervisor_next_action_determined", task_model, next_action)
        explanation = self._explain(task_model, status, stage, next_action, results, missing, human_review)
        self._audit("rcm_supervisor_task_completed", task_model, status.value)
        return SupervisorResult(
            task_id=task_model.task_id,
            claim_id=task_model.claim_id,
            status=status,
            current_stage=stage,
            workflow_stage=stage,
            next_action=next_action,
            agents_required=required,
            completed_agents=[item.agent_name for item in summaries if item.status == "COMPLETED"],
            pending_agents=pending,
            failed_agents=failed,
            human_review_required=human_review,
            priority=priority,
            risk_score=risk_score,
            reasons=reasons,
            missing_information=missing,
            agent_results=results,
            specialist_results=results,
            warnings=reasons,
            audit_reference=f"supervisor:{task_model.task_id}",
            agent_execution_summary=summaries,
            explanation=explanation,
        )

    def _refine_route(self, task: SupervisorTask, required: list[str]) -> list[str]:
        if task.task_type == SupervisorTaskType.DENIAL_REVIEW:
            category = str(task.input_data.get("denial_category", "")).upper()
            if category == "CODING" and "coding" not in required:
                required.insert(1, "coding")
            if category == "ELIGIBILITY" and "eligibility" not in required:
                required.insert(1, "eligibility")
        if task.task_type == SupervisorTaskType.FULL_RCM_REVIEW and not task.input_data.get("has_denial", True):
            required = [name for name in required if name not in {"denial", "appeal"}]
        return required

    def _invoke(self, name: str, agent: Any, claim_id: str, claim: Any) -> Any:
        if name == "claims" and hasattr(agent, "validate_claim"):
            return agent.validate_claim(claim)
        if name == "eligibility" and hasattr(agent, "process_claim"):
            return agent.process_claim(claim)
        if name == "coding" and hasattr(agent, "validate_coding"):
            return agent.validate_coding(claim)
        if name == "billing_qa" and hasattr(agent, "run_qa"):
            return agent.run_qa(claim)
        if name == "ar" and hasattr(agent, "analyze_ar"):
            return agent.analyze_ar(claim)
        if name == "appeal" and hasattr(agent, "prepare_appeal"):
            return agent.prepare_appeal(claim)
        if name == "denial" and hasattr(agent, "run"):
            return agent.run(claim_id)
        if name == "payment" and hasattr(agent, "run"):
            return agent.run(claim_id)
        if hasattr(agent, "run"):
            return agent.run(claim_id)
        return None

    @staticmethod
    def _route_based_on_denial(results: dict[str, Any], required: list[str], task: SupervisorTask, pending: list[str]) -> None:
        denial = results.get("denial")
        category = str(_value(denial, "denial_category", task.input_data.get("denial_category", ""))).upper()
        if category == "CODING" and "coding" not in required:
            required.append("coding")
            pending.append("coding")
        if category == "ELIGIBILITY" and "eligibility" not in required:
            required.append("eligibility")
            pending.append("eligibility")

    @staticmethod
    def _aggregate_risk(results: dict[str, Any], failed: list[str], pending: list[str]) -> tuple[int, SupervisorPriority, bool]:
        scores: list[int] = []
        human = bool(failed or pending)
        for result in results.values():
            risk = _value(result, "risk_score")
            if isinstance(risk, (int, float)):
                scores.append(min(int(risk), 100))
            if _value(result, "requires_human_review") or _value(result, "human_review_required"):
                human = True
            status = str(_value(result, "status", _value(result, "qa_status", "")))
            if status in {"REVIEW", "NOT_READY", "IN_PROGRESS"}:
                human = True
        risk = min(max(scores, default=0), 100)
        priority = SupervisorPriority.CRITICAL if risk >= 40 else SupervisorPriority.HIGH if risk >= 25 else SupervisorPriority.MEDIUM if risk >= 15 else SupervisorPriority.LOW
        return risk, priority, human

    @staticmethod
    def _workflow_state(task: SupervisorTask, required: list[str], results: dict[str, Any], failed: list[str], pending: list[str], human: bool) -> tuple[SupervisorStatus, str, str]:
        if failed:
            return SupervisorStatus.REVIEW, "ERROR_HANDLING", "HUMAN_REVIEW"
        if pending:
            return SupervisorStatus.WAITING, pending[0].upper(), "PROVIDE_MISSING_AGENT_RESULT"
        if human:
            return SupervisorStatus.REVIEW, required[-1].upper() if required else "HUMAN_REVIEW", "HUMAN_REVIEW"
        return SupervisorStatus.COMPLETED, required[-1].upper() if required else "COMPLETE", "NO_ACTION"

    def _explain(self, task: SupervisorTask, status: SupervisorStatus, stage: str, next_action: str, results: dict[str, Any], missing: list[str], human: bool) -> str | None:
        if self.llm_service is None:
            return None
        try:
            response = self.llm_service.generate(system_instructions="Explain only deterministic supervisor routing and specialist results. Do not change routing, status, risk, priority, or invent evidence.", user_prompt=f"Task: {task.task_type.value}\nStatus: {status.value}\nStage: {stage}\nNext action: {next_action}\nCompleted agents: {list(results)}\nMissing: {missing}\nHuman review: {human}")
            return response.response
        except LLMServiceError:
            return None

    def _audit(self, action: str, task: SupervisorTask, status: str) -> None:
        if self.audit_sink:
            self.audit_sink(action, {"task_id": task.task_id, "claim_id": task.claim_id, "status": status, "source": "synthetic_demo"})
