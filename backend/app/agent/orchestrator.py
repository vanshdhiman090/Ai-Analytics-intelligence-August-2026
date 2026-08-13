"""Build the restart-safe Ask → Prepare → Process → Analyze → Share → Act graph supervised by AnalyticsManager."""

from __future__ import annotations

import atexit
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agent.manager import manager_agent
from app.agent.workflow import DELIVERABLES, needs_approval
from app.core.config import settings
from app.domain.contracts import AnalysisPlan


class FullState(TypedDict, total=False):
    session_id: str
    file_path: str
    original_filename: str
    source_sha256: str
    business_question: str
    rough_prompt: str
    analysis_objectives: list[str]
    proposed_task: str
    analysis_brief: dict
    pending_ask_checkpoint_id: str
    business_task: str
    schema_profile: dict
    pending_checkpoint_id: str
    roccc_answers: dict
    cleaning_checklist: dict
    quality_findings: list
    final_summary: dict
    cleaned_path: str
    analysis_plan: dict
    pending_analysis_checkpoint_id: str
    analysis_plan_feedback: str
    evidence: list
    findings: list
    analysis_summary: str
    metric_semantics: dict
    root_cause_report: dict
    revenue_reporting_currency: str
    revenue_timezone: str
    baseline_period: str
    comparison_period: str
    comparison_context: dict
    period_completeness_confirmed: bool
    root_cause_hypotheses: list
    additional_deliverables: list
    chart_paths: dict
    recommendations: list
    limitations: list
    monitoring_metrics: list
    action_package: dict
    source_register: list
    join_audit: list
    cleaning_log: list
    integrity_checks: list
    validation_status: str
    quality_gates: list
    specialist_reviews: list
    quality_reviews: list
    quality_review_summary: dict
    data_intake_review: dict
    schema_review: dict
    data_quality_review: dict
    privacy_bias_review: dict
    cleaning_review: dict
    workflow_mode: str
    requested_outputs: list[str]
    report_style: str


# ── Node wrapper functions delegating to Manager Agent ────────────────────────

def propose_task_node(state: FullState) -> FullState:
    return manager_agent.propose_task(state)


def confirm_task_node(state: FullState) -> FullState:
    if not needs_approval(state, "ask"):
        return manager_agent.confirm_task(state, "Confirm")
    answer = interrupt(
        {
            "question": (
                f"Proposed primary question: \"{state['proposed_task']}\" "
                "— confirm or provide a revision."
            ),
            "stage": "ask",
            "pending_checkpoint_id": state["pending_ask_checkpoint_id"],
        }
    )
    return manager_agent.confirm_task(state, answer)


def profile_and_log_node(state: FullState) -> FullState:
    return manager_agent.profile_and_log(state)


def ask_checkpoint_node(state: FullState) -> FullState:
    if not needs_approval(state, "prepare"):
        return manager_agent.ask_checkpoint(
            state,
            "Fast analysis: local source supplied by the user. Permission and privacy must be verified before external distribution.",
        )
    answer = interrupt(
        {
            "question": "Describe the source and ROCCC status: Reliable, Original, Comprehensive, Current, Cited, plus licence/permission and any privacy restrictions.",
            "stage": "prepare",
            "pending_checkpoint_id": state["pending_checkpoint_id"],
        }
    )
    return manager_agent.ask_checkpoint(state, answer)


def process_node(state: FullState) -> FullState:
    return manager_agent.process(state)


def process_checkpoint_node(state: FullState) -> FullState:
    if not needs_approval(state, "process"):
        return {}
    answer = interrupt(
        {
            "stage": "process",
            "question": "Review the cleaning and integrity results. Type Confirm to continue to analysis, or describe a correction.",
        }
    )
    return {"process_feedback": str(answer)}


def plan_analysis_node(state: FullState) -> FullState:
    return manager_agent.plan_analysis(state)


def approve_analysis_plan_node(state: FullState) -> FullState:
    if not needs_approval(state, "analyze"):
        return {"analysis_plan_feedback": "Confirmed for fast analysis"}
    def _plan_question(plan: AnalysisPlan) -> str:
        operations = "\n".join(
            f"{item.operation_id}. {item.kind} | metric: {item.metric_column or 'n/a'} | "
            f"dimension/time: {item.dimension_column or item.time_column or 'n/a'} | "
            f"denominator: {item.denominator_column or 'n/a'} | {item.rationale}"
            for item in plan.operations
        )
        coverage = "\n".join(f"- {item}" for item in plan.question_coverage)
        return (
            "Review the proposed analysis plan before calculations begin.\n\n"
            f"Objective: {plan.objective}\n\nOperations:\n{operations}\n\nQuestion coverage:\n{coverage}\n\n"
            "Type Confirm to approve, or describe the change you want. Requested changes will be validated against the dataset."
        )

    answer = interrupt(
        {
            "stage": "analyze",
            "question": _plan_question(AnalysisPlan.model_validate(state["analysis_plan"])),
            "pending_checkpoint_id": state["pending_analysis_checkpoint_id"],
        }
    )
    return {"analysis_plan_feedback": str(answer)}


def analyze_node(state: FullState) -> FullState:
    return manager_agent.analyze(state)


def root_cause_analysis_node(state: FullState) -> FullState:
    return manager_agent.root_cause_analysis(state)


def share_node(state: FullState) -> FullState:
    return manager_agent.share(state)


def act_node(state: FullState) -> FullState:
    return manager_agent.act(state)


def package_node(state: FullState) -> FullState:
    return manager_agent.package(state)


def select_deliverables_node(state: FullState) -> FullState:
    answer = interrupt(
        {
            "stage": "deliverables",
            "question": "Your analysis is ready. Choose the deliverable(s) you want, or continue without creating a document.",
            "options": [{"id": key, "label": label} for key, label in DELIVERABLES.items()],
        }
    )
    return manager_agent.select_deliverables(state, answer)


def build_graph():
    graph = StateGraph(FullState)
    graph.add_node("propose_task", propose_task_node)
    graph.add_node("confirm_task", confirm_task_node)
    graph.add_node("profile_and_log", profile_and_log_node)
    graph.add_node("ask_checkpoint", ask_checkpoint_node)
    graph.add_node("process", process_node)
    graph.add_node("process_checkpoint", process_checkpoint_node)
    graph.add_node("plan_analysis", plan_analysis_node)
    graph.add_node("approve_analysis_plan", approve_analysis_plan_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("root_cause_analysis", root_cause_analysis_node)
    graph.add_node("share", share_node)
    graph.add_node("act", act_node)
    graph.add_node("package", package_node)
    graph.add_node("select_deliverables", select_deliverables_node)

    def route_after_process(state: FullState) -> str:
        return "plan_analysis"

    def route_after_plan_approval(state: FullState) -> str:
        if "root_cause" in state.get("analysis_objectives", []):
            return "root_cause_analysis"
        return "analyze"

    graph.set_entry_point("propose_task")
    graph.add_edge("propose_task", "confirm_task")
    graph.add_edge("confirm_task", "profile_and_log")
    graph.add_edge("profile_and_log", "ask_checkpoint")
    graph.add_edge("ask_checkpoint", "process")
    graph.add_edge("process", "process_checkpoint")
    graph.add_conditional_edges("process_checkpoint", route_after_process)
    graph.add_edge("plan_analysis", "approve_analysis_plan")
    graph.add_conditional_edges("approve_analysis_plan", route_after_plan_approval)
    graph.add_edge("analyze", "share")
    graph.add_edge("root_cause_analysis", "share")
    graph.add_edge("share", "act")
    graph.add_edge("act", "select_deliverables")
    graph.add_edge("select_deliverables", "package")
    graph.add_edge("package", END)
    return graph


_checkpoint_pool = None


def create_checkpointer():
    """Use PostgreSQL in normal runs; memory is an explicit test-only option."""
    global _checkpoint_pool
    if settings.CHECKPOINT_BACKEND == "memory":
        return MemorySaver()

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # Neon's pooled endpoint rejects PostgreSQL startup options. LangGraph needs
    # a stable session-level search_path, so use the corresponding direct host.
    checkpoint_url = settings.DATABASE_URL.replace("-pooler.", ".")
    _checkpoint_pool = ConnectionPool(
        conninfo=checkpoint_url,
        min_size=1,
        max_size=settings.CHECKPOINT_POOL_SIZE,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": "-c search_path=langgraph_checkpoints,public",
        },
        open=False,
        name="analytics-checkpoints",
    )
    _checkpoint_pool.open(wait=True)
    try:
        with _checkpoint_pool.connection() as connection:
            connection.execute("CREATE SCHEMA IF NOT EXISTS langgraph_checkpoints")
        checkpointer = PostgresSaver(_checkpoint_pool)
        checkpointer.setup()
        return checkpointer
    except Exception:
        _checkpoint_pool.close()
        _checkpoint_pool = None
        raise


def close_checkpointer() -> None:
    if _checkpoint_pool is not None:
        _checkpoint_pool.close()


checkpointer = create_checkpointer()
app = build_graph().compile(checkpointer=checkpointer)
atexit.register(close_checkpointer)
