import sys
sys.path.insert(0, "/home/claude/ai-analytics-workspace/backend")

from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel
from app.agent.process_node import process_node

db = SessionLocal()
session_row = db.query(SessionModel).order_by(SessionModel.created_at.desc()).first()
session_id = str(session_row.id)
print(f"Using existing session: {session_id}")
db.close()

result = process_node({
    "session_id": session_id,
    "file_path": "/mnt/user-data/uploads/Nike_Dataset.csv",
})

print("\n=== Cleaning Checklist ===")
for k, v in result["cleaning_checklist"].items():
    print(f"  {k}: {v}")

print("\n=== Data Quality Findings ===")
for f in result["quality_findings"]:
    print(f"  [{f['severity']}] {f['column']}: {f['issue']}")

print("\n=== Final Dataset Summary ===")
print(f"  Rows before: {result['final_summary']['rows_before']}")
print(f"  Rows after: {result['final_summary']['rows_after']}")
print(f"  Notes: {result['final_summary']['notes']}")

print("\n=== Verifying DB write ===")
db = SessionLocal()
from app.models.schema import AgentAction
action = db.query(AgentAction).filter(
    AgentAction.session_id == session_id, AgentAction.stage == "process"
).first()
print(f"AgentAction row exists: {action is not None}")
print(f"Logged code: {action.code_executed}")
db.close()
