import sys
sys.path.insert(0, "/home/claude/ai-analytics-workspace/backend")

from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel
from app.agent.analyze_node import analyze_node

db = SessionLocal()
session_row = db.query(SessionModel).order_by(SessionModel.created_at.desc()).first()
session_id = str(session_row.id)
db.close()

result = analyze_node({
    "session_id": session_id,
    "business_question": "Which sales method/retailer combination is most exposed to the "
                          "price-vs-revenue discount gap, and does it shift across regions or time?",
})

print("=== Findings ===")
for f in result["findings"]:
    print(f"\n[{f['id']}] {f['finding']}")
    print(f"  -> {f['implication']}")

print("\n=== Analysis Summary ===")
print(result["analysis_summary"])

print("\n=== Additional Deliverables for Further Exploration ===")
for d in result["additional_deliverables"]:
    print(f"  - {d}")

print("\n=== Verifying DB write ===")
db = SessionLocal()
from app.models.schema import AgentAction
action = db.query(AgentAction).filter(
    AgentAction.session_id == session_id, AgentAction.stage == "analyze"
).first()
print(f"AgentAction row exists: {action is not None}")
db.close()
