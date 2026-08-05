"""
Milestone 6 — Full orchestration. Wires Prepare -> Process -> Analyze ->
Share -> Act into one continuous graph. Ask is deferred (needs live LLM
call) — this proves the deterministic five-stage backbone end-to-end.

Known fixes applied proactively (found during individual node testing):
- All numeric values cast to native Python types before touching state.
- interrupt() is the first action in its node, no side effects before it.
- No field named 'checkpoint_id' (reserved by LangGraph internals).
"""

import sys
sys.path.insert(0, "/home/claude/ai-analytics-workspace/backend")

from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.ask_node import propose_task_node, confirm_task_node
from app.agent.prepare_node import profile_and_log_node, ask_checkpoint_node
from app.agent.process_node import process_node
from app.agent.analyze_node import analyze_node
from app.agent.share_node import share_node
from app.agent.act_node import act_node


class FullState(TypedDict, total=False):
    session_id: str
    file_path: str
    business_question: str
    rough_prompt: str
    proposed_task: str
    pending_ask_checkpoint_id: str
    business_task: str
    schema_profile: dict
    pending_checkpoint_id: str
    roccc_answers: dict
    cleaning_checklist: dict
    quality_findings: list
    final_summary: dict
    findings: list
    analysis_summary: str
    additional_deliverables: list
    chart_paths: dict
    recommendations: list
    limitations: list


graph = StateGraph(FullState)
graph.add_node("propose_task", propose_task_node)
graph.add_node("confirm_task", confirm_task_node)
graph.add_node("profile_and_log", profile_and_log_node)
graph.add_node("ask_checkpoint", ask_checkpoint_node)
graph.add_node("process", process_node)
graph.add_node("analyze", analyze_node)
graph.add_node("share", share_node)
graph.add_node("act", act_node)

graph.set_entry_point("propose_task")
graph.add_edge("propose_task", "confirm_task")
graph.add_edge("confirm_task", "profile_and_log")
graph.add_edge("profile_and_log", "ask_checkpoint")
graph.add_edge("ask_checkpoint", "process")
graph.add_edge("process", "analyze")
graph.add_edge("analyze", "share")
graph.add_edge("share", "act")
graph.add_edge("act", END)

checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)
