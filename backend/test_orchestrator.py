import sys
sys.path.insert(0, "/home/claude/ai-analytics-workspace/backend")

import uuid
from langgraph.types import Command
from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel
from app.agent.orchestrator import app as pipeline

db = SessionLocal()
session_row = SessionModel(user_id=uuid.uuid4(), business_task="Full pipeline test")
db.add(session_row)
db.commit()
session_id = str(session_row.id)
db.close()
print(f"Session: {session_id}")

config = {"configurable": {"thread_id": session_id}}

result = pipeline.invoke({
    "session_id": session_id,
    "file_path": "/mnt/user-data/uploads/Nike_Dataset.csv",
    "business_question": "Which sales method/retailer combination is most exposed to the "
                          "price-vs-revenue discount gap?",
}, config=config)

print("PAUSED at checkpoint:", result.get("__interrupt__") is not None)

final = pipeline.invoke(
    Command(resume="Downloaded from Kaggle, public domain, BI practice dataset"),
    config=config,
)

print("\n=== FULL PIPELINE COMPLETE ===")
print(f"Findings: {len(final.get('findings', []))}")
print(f"Charts: {list(final.get('chart_paths', {}).keys())}")
print(f"Recommendations: {len(final.get('recommendations', []))}")
print(f"Limitations: {len(final.get('limitations', []))}")

print("\n=== DB verification ===")
db = SessionLocal()
from app.models.schema import Dataset, Checkpoint, AgentAction, Artifact
print(f"Datasets: {db.query(Dataset).filter(Dataset.session_id==session_id).count()}")
print(f"Checkpoints: {db.query(Checkpoint).filter(Checkpoint.session_id==session_id).count()}")
print(f"AgentActions: {db.query(AgentAction).filter(AgentAction.session_id==session_id).count()}")
print(f"Artifacts: {db.query(Artifact).filter(Artifact.session_id==session_id).count()}")
db.close()
