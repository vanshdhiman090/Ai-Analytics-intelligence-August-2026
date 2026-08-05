import sys
sys.path.insert(0, "/home/claude/ai-analytics-workspace/backend")

from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel
from app.agent.analyze_node import analyze_node
from app.agent.share_node import share_node
from app.agent.act_node import act_node

db = SessionLocal()
session_row = db.query(SessionModel).order_by(SessionModel.created_at.desc()).first()
session_id = str(session_row.id)
db.close()

# Re-run analyze to get findings in memory (already logged to DB, just need the data here)
analyze_result = analyze_node({
    "session_id": session_id,
    "business_question": "Which sales method/retailer combination is most exposed to the "
                          "price-vs-revenue discount gap?",
})

print("=== Running Share node ===")
share_result = share_node({"session_id": session_id, "findings": analyze_result["findings"]})
print(f"Charts generated: {list(share_result['chart_paths'].keys())}")

print("\n=== Running Act node ===")
act_result = act_node({"session_id": session_id, "findings": analyze_result["findings"]})
print(f"Recommendations: {len(act_result['recommendations'])}")
for r in act_result["recommendations"]:
    print(f"  [P{r['priority']}] {r['recommendation'][:70]}... (cites {r['supporting_findings']})")
print(f"Limitations documented: {len(act_result['limitations'])}")

print("\n=== Verifying full pipeline in DB ===")
db = SessionLocal()
from app.models.schema import Artifact, AgentAction
artifacts = db.query(Artifact).filter(Artifact.session_id == session_id).all()
actions = db.query(AgentAction).filter(AgentAction.session_id == session_id).order_by(AgentAction.created_at).all()
print(f"Total artifacts (charts + report): {len(artifacts)}")
print(f"Full agent_actions trail, in order:")
for a in actions:
    print(f"  [{a.stage}] {a.action_type}")
db.close()
