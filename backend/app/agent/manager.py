"""Chief analytics manager and bounded professional specialist workforce."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from app.agent.hierarchy import MANAGERS, SPECIALISTS, SPECIALIST_TO_MANAGER, ManagerProfile, hierarchy_catalogue
from app.agent.package_node import validate_package
from app.agent.specialist_contracts import (
    ContractValue,
    IdempotencyMetadata,
    RetryDisposition,
    SpecialistResult,
    SpecialistResultStatus,
    SpecialistTask,
    TaskContext,
    build_idempotency_key,
    classify_error,
    fingerprint_inputs,
    sanitize_diagnostic,
    validate_specialist_result,
)
from app.agent.subagents.act_agent import ActAgent
from app.agent.subagents.analyze_agent import AnalyzeAgent
from app.agent.subagents.ask_agent import AskAgent
from app.agent.subagents.data_specialists import (
    CleaningSpecialist,
    DataIntakeSpecialist,
    DataQualitySpecialist,
    PrivacyBiasSpecialist,
    SchemaSpecialist,
)
from app.agent.subagents.memory_curator import MemoryCuratorSpecialist
from app.agent.subagents.package_agent import PackageAgent
from app.agent.subagents.prepare_agent import PrepareAgent
from app.agent.subagents.process_agent import ProcessAgent
from app.agent.subagents.professional_specialists import (
    AnalysisPlannerSpecialist,
    BusinessProblemSpecialist,
    DocumentSpecialist,
    EvidenceSpecialist,
    KPISpecialist,
    NarrativeSpecialist,
    RecommendationSpecialist,
    StakeholderScopeSpecialist,
    StatisticalAnalysisSpecialist,
    TrendSegmentationSpecialist,
    VisualizationSpecialist,
)
from app.agent.subagents.quality_specialists import (
    CalculationReviewer,
    CausalLanguageReviewer,
    EvidenceCritic,
    PublicationReviewer,
)
from app.agent.subagents.root_cause_agent import RootCauseAgent
from app.agent.subagents.share_agent import ShareAgent
from app.agent.workflow import parse_deliverable_selection
from app.core.database import SessionLocal
from app.domain.contracts import ActionPackage
from app.models.schema import AgentAction
from app.services.learning_memory import LearningMemoryStore, learning_memory
from app.services.comparison_context import extract_explicit_comparison_context
from app.services.progress import emit_sync

logger = logging.getLogger(__name__)


# Actual workflow fields each specialist is permitted to receive.  The manager
# adds only its brief and validated lessons.  This list is deliberately kept
# separate from the human-readable role catalogue so it can be tested as an
# executable least-privilege boundary.
SPECIALIST_INPUT_FIELDS: dict[str, tuple[str, ...]] = {
    "BusinessProblemSpecialist": (
        "session_id", "rough_prompt", "analysis_objectives", "workflow_mode", "proposed_task",
        "analysis_brief", "pending_ask_checkpoint_id",
    ),
    "StakeholderScopeSpecialist": ("session_id", "analysis_brief", "business_question"),
    "KPISpecialist": ("session_id", "analysis_brief", "business_question"),
    "DataIntakeSpecialist": ("session_id", "file_path", "original_filename", "source_sha256", "source_register"),
    "PrepareAgent": (
        "session_id", "file_path", "original_filename", "source_sha256", "source_register",
        "pending_checkpoint_id", "business_question", "schema_profile",
    ),
    "SchemaSpecialist": ("session_id", "schema_profile", "source_register"),
    "DataQualitySpecialist": ("session_id", "schema_profile", "quality_findings", "integrity_checks", "validation_status"),
    "PrivacyBiasSpecialist": ("session_id", "schema_profile", "roccc_answers", "source_register"),
    "ProcessAgent": ("session_id", "file_path", "join_audit"),
    "CleaningSpecialist": (
        "session_id", "cleaned_path", "final_summary", "cleaning_checklist", "cleaning_log",
        "integrity_checks", "validation_status",
    ),
    "AnalysisPlannerSpecialist": (
        "session_id", "business_question", "cleaned_path", "schema_profile", "analysis_brief",
        "analysis_objectives", "workflow_mode", "comparison_context",
    ),
    "StatisticalAnalysisSpecialist": (
        "session_id", "business_question", "cleaned_path", "schema_profile", "analysis_brief",
        "analysis_objectives", "analysis_plan", "analysis_plan_feedback", "workflow_mode", "comparison_context",
    ),
    "TrendSegmentationSpecialist": ("session_id", "analysis_plan", "analysis_objectives", "schema_profile"),
    "RootCauseAgent": (
        "session_id", "business_question", "cleaned_path", "schema_profile", "analysis_brief",
        "analysis_objectives", "analysis_plan", "analysis_plan_feedback", "workflow_mode",
        "revenue_reporting_currency", "revenue_timezone", "baseline_period", "comparison_period",
        "period_completeness_confirmed", "root_cause_hypotheses", "comparison_context",
    ),
    "EvidenceSpecialist": ("session_id", "evidence", "findings", "analysis_plan", "comparison_context"),
    "VisualizationSpecialist": ("session_id", "evidence", "findings", "comparison_context"),
    "NarrativeSpecialist": ("session_id", "analysis_summary", "findings", "limitations", "chart_paths"),
    "RecommendationSpecialist": (
        "session_id", "business_question", "analysis_brief", "evidence", "findings", "workflow_mode",
    ),
    "CalculationReviewer": (
        "session_id", "analysis_plan", "evidence", "validation_status", "integrity_checks", "quality_reviews", "comparison_context", "root_cause_report",
    ),
    "EvidenceCritic": ("session_id", "evidence", "findings", "recommendations", "quality_reviews"),
    "CausalLanguageReviewer": ("session_id", "evidence", "findings", "quality_reviews"),
    "PublicationReviewer": ("session_id", "quality_gates", "quality_reviews"),
    "DocumentSpecialist": (
        "session_id", "business_question", "original_filename", "source_sha256", "cleaned_path",
        "analysis_brief", "analysis_summary", "schema_profile", "source_register", "roccc_answers",
        "cleaning_checklist", "cleaning_log", "integrity_checks", "validation_status", "quality_findings",
        "final_summary", "analysis_plan", "evidence", "findings", "chart_paths", "action_package",
        "recommendations", "limitations", "monitoring_metrics", "additional_deliverables", "quality_gates",
        "quality_reviews", "requested_outputs", "report_style", "metric_semantics", "root_cause_report", "comparison_context",
    ),
}


@dataclass(frozen=True)
class DomainManager:
    """A bounded supervisor responsible for a related group of specialists."""

    profile: ManagerProfile

    def prepare_assignment(
        self,
        state: dict[str, Any],
        specialist_name: str,
        lessons: list[Any],
        task: SpecialistTask | None = None,
    ) -> dict[str, Any]:
        if specialist_name not in self.profile.specialists:
            raise ValueError(f"{self.profile.name} cannot supervise {specialist_name}")
        permitted = SPECIALIST_INPUT_FIELDS.get(specialist_name, ())
        assignment = {field: state[field] for field in permitted if field in state}
        specialist_profile = SPECIALISTS[specialist_name]
        assignment["_manager_brief"] = {
            "manager": self.profile.name,
            "manager_mission": self.profile.mission,
            "specialist": specialist_name,
            "specialist_mission": specialist_profile.mission,
            "responsibilities": list(specialist_profile.responsibilities),
            "expected_outputs": list(specialist_profile.outputs),
            "quality_gates": list(specialist_profile.quality_gates),
            "allowed_actions": list(specialist_profile.allowed_actions),
            "escalation_conditions": list(specialist_profile.escalation_conditions),
            "task_contract": task.model_dump(mode="json") if task else None,
        }
        assignment["_learning_lessons"] = [
            f"{lesson.error_summary} {lesson.guidance}" for lesson in lessons
        ]
        return assignment


class AnalyticsManager:
    """Plan, delegate, validate, review, and audit the analytics workforce."""

    def __init__(self, memory_store: LearningMemoryStore | None = None) -> None:
        # Trusted stage executors are retained behind focused specialist adapters.
        self.ask_agent = AskAgent()
        self.prepare_agent = PrepareAgent()
        self.process_agent = ProcessAgent()
        self.analyze_agent = AnalyzeAgent()
        self.share_agent = ShareAgent()
        self.act_agent = ActAgent()
        self.package_agent = PackageAgent()
        self.root_cause_agent = RootCauseAgent()

        store = memory_store or learning_memory
        self.memory_store = store  # Backward-compatible test and service access.
        self.memory_curator = MemoryCuratorSpecialist(store)
        specialists = (
            BusinessProblemSpecialist(self.ask_agent), StakeholderScopeSpecialist(), KPISpecialist(),
            DataIntakeSpecialist(), self.prepare_agent, SchemaSpecialist(), DataQualitySpecialist(),
            PrivacyBiasSpecialist(), self.process_agent, CleaningSpecialist(),
            AnalysisPlannerSpecialist(self.analyze_agent), StatisticalAnalysisSpecialist(self.analyze_agent),
            TrendSegmentationSpecialist(), self.root_cause_agent, EvidenceSpecialist(),
            VisualizationSpecialist(self.share_agent), NarrativeSpecialist(),
            RecommendationSpecialist(self.act_agent), DocumentSpecialist(self.package_agent),
            CalculationReviewer(), EvidenceCritic(), CausalLanguageReviewer(), PublicationReviewer(),
            self.memory_curator,
        )
        self.specialist_registry = {specialist.name: specialist for specialist in specialists}
        missing_runtime = set(SPECIALISTS) - set(self.specialist_registry)
        if missing_runtime:
            raise RuntimeError(f"Declared specialists have no runtime implementation: {sorted(missing_runtime)}")
        self.domain_managers = {name: DomainManager(profile) for name, profile in MANAGERS.items()}

    @staticmethod
    def describe_hierarchy() -> dict[str, Any]:
        return hierarchy_catalogue()

    def manager_for(self, specialist_name: str) -> DomainManager:
        manager_name = SPECIALIST_TO_MANAGER.get(specialist_name)
        if manager_name is None:
            raise ValueError(f"No domain manager is registered for {specialist_name}")
        return self.domain_managers[manager_name]

    def _log_supervision(
        self, session_id: str, stage: str, subagent_name: str, status: str, details: str
    ) -> None:
        db = SessionLocal()
        try:
            db.add(
                AgentAction(
                    session_id=session_id,
                    stage=stage,
                    action_type="manager_supervision",
                    input_summary=(
                        f"{SPECIALIST_TO_MANAGER.get(subagent_name, 'AnalyticsManager')} supervising "
                        f"[{subagent_name}] in stage '{stage}'"
                    ),
                    output_summary=f"Status: {status} | {sanitize_diagnostic(details)}",
                )
            )
            db.commit()
        except Exception:
            logger.exception("Failed to write manager supervision audit log")
        finally:
            db.close()

    @staticmethod
    def _task_for(
        state: dict[str, Any], specialist_name: str, stage: str, manager_name: str,
        expected_outputs: tuple[str, ...], attempt: int, max_attempts: int,
    ) -> SpecialistTask:
        permitted = SPECIALIST_INPUT_FIELDS.get(specialist_name, ())
        selected = {field: state[field] for field in permitted if field in state}
        safe_identity = {
            "session_id": str(state.get("session_id", "unknown")),
            "specialist": specialist_name,
            "stage": stage,
            "source_sha256": str(state.get("source_sha256", "not-recorded")),
        }
        input_fingerprint = fingerprint_inputs(safe_identity)
        idempotency_key = build_idempotency_key(
            session_id=safe_identity["session_id"], specialist_name=specialist_name,
            task_type=stage, input_fingerprint=input_fingerprint,
        )
        task_id = f"{safe_identity['session_id']}:{stage}:{specialist_name}"
        return SpecialistTask(
            task_id=task_id[:128],
            task_type=f"{stage}_specialist_task",
            objective=SPECIALISTS[specialist_name].mission,
            context=TaskContext(
                session_id=safe_identity["session_id"], trace_id=f"{safe_identity['session_id']}:{stage}"[:128],
                manager_name=manager_name, specialist_name=specialist_name, stage=stage,
                workflow_mode=str(state.get("workflow_mode") or "professional"),
            ),
            idempotency=IdempotencyMetadata(
                key=idempotency_key, attempt=attempt, max_attempts=max_attempts,
                input_fingerprint=input_fingerprint, side_effect_free=specialist_name not in {
                    "BusinessProblemSpecialist", "PrepareAgent", "ProcessAgent", "AnalysisPlannerSpecialist",
                    "StatisticalAnalysisSpecialist", "RootCauseAgent", "VisualizationSpecialist",
                    "RecommendationSpecialist", "DocumentSpecialist",
                },
            ),
            required_inputs=tuple(selected),
            required_outputs=expected_outputs,
            inputs=tuple(ContractValue(name=key, value=value) for key, value in selected.items()),
        )

    def run_subagent_with_healing(
        self,
        subagent: Any,
        state: dict[str, Any],
        workflow_stage: str,
        max_retries: int = 3,
        expected_outputs: tuple[str, ...] = (),
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute one bounded specialist and retry only classified transient failures."""
        session_id = str(state.get("session_id", "unknown"))
        failed_fingerprints: list[str] = []
        domain_manager = self.manager_for(subagent.name)
        last_exception: Exception | None = None

        for attempt in range(1, max_retries + 1):
            started = time.perf_counter()
            task = self._task_for(
                state, subagent.name, workflow_stage, domain_manager.profile.name,
                expected_outputs or ("result",), attempt, max_retries,
            )
            try:
                lessons = self.memory_curator.recall(subagent.name, workflow_stage)
            except Exception:
                lessons = []
                logger.exception("Learning memory recall failed; continuing without prior lessons")
            assignment = domain_manager.prepare_assignment(state, subagent.name, lessons, task)

            try:
                result = subagent.execute(assignment, **kwargs)
                if not isinstance(result, dict):
                    raise TypeError(f"{subagent.name} returned {type(result).__name__}; a mapping is required")
                if expected_outputs:
                    contract_result = SpecialistResult(
                        result_id=f"{task.task_id}:attempt-{attempt}"[:128], task_id=task.task_id,
                        specialist_name=subagent.name, status=SpecialistResultStatus.COMPLETED,
                        outputs=tuple(ContractValue(name=key, value=value) for key, value in result.items()),
                    )
                    validate_specialist_result(task, contract_result)

                for fingerprint in failed_fingerprints:
                    try:
                        self.memory_curator.record_recovery(
                            specialist=subagent.name, stage=workflow_stage, fingerprint=fingerprint, attempt=attempt
                        )
                    except Exception:
                        logger.exception("Learning memory recovery write failed")
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._log_supervision(
                    session_id, workflow_stage, subagent.name, "SUCCESS",
                    f"Task {task.task_id}; attempt {attempt}; {elapsed_ms} ms; validated outputs: {sorted(result)}",
                )
                return result
            except Exception as exc:
                last_exception = exc
                classification = classify_error(exc)
                try:
                    fingerprint = self.memory_curator.record_failure(
                        session_id=session_id, manager=domain_manager.profile.name,
                        specialist=subagent.name, stage=workflow_stage, error=exc,
                    )
                    if fingerprint not in failed_fingerprints:
                        failed_fingerprints.append(fingerprint)
                except Exception:
                    logger.exception("Learning memory failure write failed")
                will_retry = (
                    attempt < max_retries
                    and classification.retry in {RetryDisposition.IMMEDIATE, RetryDisposition.BACKOFF}
                    and task.idempotency.side_effect_free
                )
                self._log_supervision(
                    session_id, workflow_stage, subagent.name, "RETRY_NEEDED" if will_retry else "FAILED",
                    f"Task {task.task_id}; attempt {attempt}; {classification.code}: {classification.summary}",
                )
                if not will_retry:
                    break
                delay = min(0.25 * (2 ** (attempt - 1)), 1.0)
                emit_sync(session_id, workflow_stage, f"[Manager] Safe recovery retry {attempt + 1}/{max_retries} for [{subagent.name}]…")
                time.sleep(delay)

        if last_exception is not None:
            raise last_exception
        raise RuntimeError(f"{subagent.name} did not produce a result")

    def _run_team(
        self,
        state: dict[str, Any],
        stage: str,
        assignments: Iterable[tuple[Any, tuple[str, ...], dict[str, Any]]],
    ) -> dict[str, Any]:
        working = dict(state)
        updates: dict[str, Any] = {}
        for specialist, expected_outputs, kwargs in assignments:
            result = self.run_subagent_with_healing(
                specialist, working, stage, expected_outputs=expected_outputs, **kwargs
            )
            working.update(result)
            updates.update(result)
        return updates

    def _run_quality_team(
        self, state: dict[str, Any], stage: str, reviewers: tuple[Any, ...]
    ) -> dict[str, Any]:
        working = dict(state)
        updates: dict[str, Any] = {}
        for reviewer in reviewers:
            result = self.run_subagent_with_healing(
                reviewer, working, stage, expected_outputs=("quality_reviews",), stage=stage
            )
            working.update(result)
            updates.update(result)
        current = [item for item in working.get("quality_reviews", []) if item.get("stage") == stage]
        failed = [item for item in current if item.get("status") == "fail" and item.get("blocking")]
        updates["quality_review_summary"] = {
            "stage": stage,
            "status": "fail" if failed else "pass",
            "failed_reviewers": [item.get("reviewer") for item in failed],
            "reviewed_by": [item.get("reviewer") for item in current],
        }
        if failed:
            reasons = "; ".join(str(item.get("summary")) for item in failed)
            raise ValueError(f"Independent quality review requires revision: {reasons}")
        return updates

    # Public stage methods called by the LangGraph controller.
    def propose_task(self, state: dict[str, Any]) -> dict[str, Any]:
        updates = self._run_team(state, "ask", (
            (self.specialist_registry["BusinessProblemSpecialist"], ("analysis_brief", "proposed_task", "pending_ask_checkpoint_id"), {"phase": "propose"}),
        ))
        return self._run_team({**state, **updates}, "ask", (
            (self.specialist_registry["StakeholderScopeSpecialist"], ("specialist_reviews",), {}),
            (self.specialist_registry["KPISpecialist"], ("specialist_reviews",), {}),
        )) | updates

    def confirm_task(self, state: dict[str, Any], answer: Any = None) -> dict[str, Any]:
        updates = self._run_team(state, "ask", (
            (self.specialist_registry["BusinessProblemSpecialist"], ("business_task", "business_question", "analysis_brief"), {"phase": "confirm", "answer": answer}),
        ))
        context = extract_explicit_comparison_context({**state, **updates})
        if context is not None:
            updates["comparison_context"] = context.model_dump(mode="json")
            updates["baseline_period"] = context.baseline_period
            updates["comparison_period"] = context.comparison_period
        return updates

    def profile_and_log(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_team(state, "prepare", (
            (self.specialist_registry["DataIntakeSpecialist"], ("data_intake_review",), {}),
            (self.prepare_agent, ("schema_profile", "source_register", "pending_checkpoint_id"), {"phase": "profile"}),
            (self.specialist_registry["SchemaSpecialist"], ("schema_review",), {}),
        ))

    def ask_checkpoint(self, state: dict[str, Any], answer: Any = None) -> dict[str, Any]:
        return self._run_team(state, "prepare", (
            (self.prepare_agent, ("roccc_answers", "source_register"), {"phase": "roccc", "answer": answer}),
            (self.specialist_registry["PrivacyBiasSpecialist"], ("privacy_bias_review",), {}),
        ))

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._run_team(state, "process", (
            (self.process_agent, ("cleaned_path", "cleaning_checklist", "cleaning_log", "integrity_checks", "validation_status", "quality_findings", "final_summary"), {}),
            (self.specialist_registry["DataQualitySpecialist"], ("data_quality_review",), {}),
            (self.specialist_registry["CleaningSpecialist"], ("cleaning_review",), {}),
        ))

    def plan_analysis(self, state: dict[str, Any]) -> dict[str, Any]:
        updates = self._run_team(state, "analyze", (
            (self.specialist_registry["AnalysisPlannerSpecialist"], ("analysis_plan", "pending_analysis_checkpoint_id"), {}),
        ))
        return updates | self._run_team({**state, **updates}, "analyze", (
            (self.specialist_registry["TrendSegmentationSpecialist"], ("specialist_reviews",), {}),
        ))

    def _analyze_with(self, state: dict[str, Any], specialist: Any) -> dict[str, Any]:
        updates = self._run_team(state, "analyze", (
            (specialist, ("analysis_plan", "evidence", "findings", "analysis_summary"), {}),
        ))
        evidence_review = self._run_team({**state, **updates}, "analyze", (
            (self.specialist_registry["EvidenceSpecialist"], ("specialist_reviews",), {}),
        ))
        working = {**state, **updates, **evidence_review}
        quality = self._run_quality_team(
            working, "analyze",
            (self.specialist_registry["CalculationReviewer"], self.specialist_registry["EvidenceCritic"], self.specialist_registry["CausalLanguageReviewer"]),
        )
        return updates | evidence_review | quality

    def analyze(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._analyze_with(state, self.specialist_registry["StatisticalAnalysisSpecialist"])

    def root_cause_analysis(self, state: dict[str, Any]) -> dict[str, Any]:
        updates = self._run_team(state, "analyze", (
            (
                self.root_cause_agent,
                (
                    "analysis_plan", "evidence", "findings", "analysis_summary",
                    "metric_semantics", "root_cause_report",
                ),
                {},
            ),
        ))
        evidence_review = self._run_team({**state, **updates}, "analyze", (
            (self.specialist_registry["EvidenceSpecialist"], ("specialist_reviews",), {}),
        ))
        working = {**state, **updates, **evidence_review}
        quality = self._run_quality_team(
            working,
            "analyze",
            (
                self.specialist_registry["CalculationReviewer"],
                self.specialist_registry["EvidenceCritic"],
                self.specialist_registry["CausalLanguageReviewer"],
            ),
        )
        return updates | evidence_review | quality

    def share(self, state: dict[str, Any]) -> dict[str, Any]:
        updates = self._run_team(state, "share", (
            (self.specialist_registry["VisualizationSpecialist"], ("chart_paths",), {}),
            (self.specialist_registry["NarrativeSpecialist"], ("specialist_reviews",), {}),
        ))
        quality = self._run_quality_team(
            {**state, **updates}, "share",
            (self.specialist_registry["EvidenceCritic"], self.specialist_registry["CausalLanguageReviewer"]),
        )
        return updates | quality

    def act(self, state: dict[str, Any]) -> dict[str, Any]:
        updates = self._run_team(state, "act", (
            (self.specialist_registry["RecommendationSpecialist"], ("action_package", "recommendations", "limitations", "monitoring_metrics"), {}),
        ))
        quality = self._run_quality_team(
            {**state, **updates}, "act",
            (self.specialist_registry["EvidenceCritic"], self.specialist_registry["CausalLanguageReviewer"]),
        )
        return updates | quality

    def package(self, state: dict[str, Any]) -> dict[str, Any]:
        package = ActionPackage.model_validate(state["action_package"])
        gates = validate_package(state, package)
        preflight = {**state, "quality_gates": gates}
        quality = self._run_quality_team(
            preflight, "package", (self.specialist_registry["PublicationReviewer"],)
        )
        updates = self._run_team({**preflight, **quality}, "package", (
            (self.specialist_registry["DocumentSpecialist"], ("quality_gates",), {}),
        ))
        return {"quality_gates": gates} | quality | updates

    def select_deliverables(self, state: dict[str, Any], answer: Any) -> dict[str, Any]:
        """Keep release selection as an explicit user decision, never an LLM decision."""
        return parse_deliverable_selection(answer)


manager_agent = AnalyticsManager()
