"""
Day One, Step 4: smallest possible LangGraph proving pause/resume works.

This is deliberately trivial — one node, one interrupt — before we port
any real Prepare/Process/Analyze logic in. If this doesn't work, nothing
built on top of it will either.
"""

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver
from typing import TypedDict


class State(TypedDict):
    dataset_name: str
    data_source_answer: str


def ask_node(state: State) -> State:
    """Simulates a 'Ground or Ask' checkpoint: the agent cannot know the
    data source on its own, so it interrupts and waits for a human answer."""
    answer = interrupt({
        "question": f"Where did '{state['dataset_name']}' come from?",
        "stage": "prepare",
    })
    return {"data_source_answer": answer}


def confirm_node(state: State) -> State:
    print(f"[agent] Resumed successfully. Human answered: '{state['data_source_answer']}'")
    return state


graph = StateGraph(State)
graph.add_node("ask_checkpoint", ask_node)
graph.add_node("confirm", confirm_node)
graph.set_entry_point("ask_checkpoint")
graph.add_edge("ask_checkpoint", "confirm")
graph.add_edge("confirm", END)

checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    config = {"configurable": {"thread_id": "test-session-1"}}

    print("=== First run: should PAUSE at the checkpoint ===")
    result = app.invoke({"dataset_name": "example_dataset.csv", "data_source_answer": ""}, config=config)
    print(f"Graph state after pause: {result}")

    state_snapshot = app.get_state(config)
    print(f"Is it actually paused? next node(s) waiting: {state_snapshot.next}")

    print("\n=== Simulating: time passes, human comes back later and answers ===")
    print("=== Resuming from EXACTLY where it paused, not from scratch ===")
    result = app.invoke(Command(resume="Downloaded from Kaggle, public dataset"), config=config)
    print(f"Final state: {result}")
