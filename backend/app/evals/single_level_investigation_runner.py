"""Answer-keyed Milestone 1 benchmark through the actual RootCauseAgent path."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent


def run_benchmark(cases_path: Path | None = None) -> dict[str, object]:
    cases_path = cases_path or Path(__file__).resolve().parents[2] / "evals" / "single_level_investigation_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        for case in cases:
            csv_path = Path(directory) / f"{case['id']}.csv"
            pd.DataFrame(case["rows"]).to_csv(csv_path, index=False)
            actual = RootCauseAgent().execute({"cleaned_path": str(csv_path), "investigation_request": case["request"]})["investigation_state"]
            expected = case["expected"]
            mismatches = {key: {"expected": value, "actual": actual.get(key)} for key, value in expected.items() if actual.get(key) != value}
            results.append({"id": case["id"], "passed": not mismatches, "mismatches": mismatches})
    passed = sum(item["passed"] for item in results)
    return {"total": len(results), "passed": passed, "failed": len(results) - passed, "release_ready": passed == len(results), "results": results}


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
