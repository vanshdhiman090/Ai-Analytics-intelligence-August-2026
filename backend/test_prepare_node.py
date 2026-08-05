import sys
sys.path.insert(0, "/home/claude/ai-analytics-workspace/backend")

import uuid
from langgraph.types import Command
from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel
from app.agent.prepare_node import app as prepare_app

# 1. Create a real session row first (a real run needs a real session)
db = SessionLocal()
session_row = SessionModel(user_id=uuid.uuid4(), business_task="Test run — discount gap analysis")
db.add(session_row)
db.commit()
session_id = str(session_row.id)
print(f"Created session: {session_id}")
db.close()

config = {"configurable": {"thread_id": session_id}}

# 2. Run the Prepare node — should pause at the ROCCC checkpoint
print("\n=== Running Prepare node ===")
result = prepare_app.invoke(
    {"session_id": session_id, "file_path": "/mnt/user-data/uploads/Nike_Dataset.csv"},
    config=config,
)
print("Paused. Interrupt payload:", result.get("__interrupt__"))

# 3. Resume with a real answer
print("\n=== Resuming with human answer ===")
final = prepare_app.invoke(
    Command(resume="Downloaded from Kaggle, public domain, used for BI portfolio practice"),
    config=config,
)
print("Final state row count:", final["schema_profile"]["row_count"])

# 4. Verify it's ACTUALLY in the database, not just in-memory
print("\n=== Verifying real DB writes ===")
db = SessionLocal()
from app.models.schema import Dataset, Checkpoint, AgentAction
ds = db.query(Dataset).filter(Dataset.session_id == session_id).first()
cp = db.query(Checkpoint).filter(Checkpoint.session_id == session_id).first()
aa = db.query(AgentAction).filter(AgentAction.session_id == session_id).first()
print(f"Dataset row exists: {ds is not None}, row_count stored: {ds.row_count}")
print(f"Checkpoint row exists: {cp is not None}, answer stored: '{cp.answer}'")
print(f"AgentAction row exists: {aa is not None}, output: {aa.output_summary[:80]}...")
db.close()
