"""Deterministic multi-table relationship discovery and safe model materialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.tabular import json_value, load_dataframe, profile_dataframe


class DataModelError(ValueError):
    """Raised when a proposed data model would produce unsafe or ambiguous results."""


@dataclass(frozen=True)
class ModelSource:
    dataset_id: str
    filename: str
    path: Path
    sha256: str | None = None


def _key_stats(series: pd.Series) -> dict[str, Any]:
    observed = series.dropna()
    return {
        "observed": int(len(observed)),
        "unique": int(observed.nunique(dropna=True)),
        "nulls": int(series.isna().sum()),
        "is_unique": bool(len(observed) > 0 and not observed.duplicated().any()),
    }


def _compatible(left: pd.Series, right: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
        return True
    return not (pd.api.types.is_numeric_dtype(left) ^ pd.api.types.is_numeric_dtype(right))


def _relationship(left_source: ModelSource, right_source: ModelSource, key: str, left: pd.DataFrame, right: pd.DataFrame) -> dict[str, Any]:
    left_stats = _key_stats(left[key])
    right_stats = _key_stats(right[key])
    left_values = set(left[key].dropna().astype(str))
    right_values = set(right[key].dropna().astype(str))
    overlap = left_values & right_values
    left_coverage = len(overlap) / max(len(left_values), 1)
    right_coverage = len(overlap) / max(len(right_values), 1)
    if left_stats["is_unique"] and right_stats["is_unique"]:
        cardinality = "one_to_one"
    elif right_stats["is_unique"]:
        cardinality = "many_to_one"
    elif left_stats["is_unique"]:
        cardinality = "one_to_many"
    else:
        cardinality = "many_to_many"
    score = round((0.55 * max(left_coverage, right_coverage)) + (0.35 if cardinality != "many_to_many" else 0) + (0.10 if key.lower().endswith(("id", "_key")) else 0), 3)
    blocked = cardinality == "many_to_many" or not overlap
    warnings: list[str] = []
    if cardinality == "many_to_many":
        warnings.append("Both tables repeat this key; joining would multiply rows.")
    if left_coverage < 0.8:
        warnings.append(f"{left_coverage:.1%} of distinct left keys match the right table.")
    if right_coverage < 0.8:
        warnings.append(f"{right_coverage:.1%} of distinct right keys match the left table.")
    return {
        "relationship_id": f"{left_source.dataset_id}:{right_source.dataset_id}:{key}",
        "left_dataset_id": left_source.dataset_id,
        "left_filename": left_source.filename,
        "right_dataset_id": right_source.dataset_id,
        "right_filename": right_source.filename,
        "left_key": key,
        "right_key": key,
        "cardinality": cardinality,
        "left_unique": left_stats["is_unique"],
        "right_unique": right_stats["is_unique"],
        "left_match_rate": round(left_coverage, 4),
        "right_match_rate": round(right_coverage, 4),
        "overlapping_keys": len(overlap),
        "confidence_score": score,
        "recommended": bool(not blocked and score >= 0.7),
        "blocked": blocked,
        "warnings": warnings,
    }


def inspect_data_model(sources: list[ModelSource]) -> dict[str, Any]:
    if not 1 <= len(sources) <= 10:
        raise DataModelError("Select between 1 and 10 datasets.")
    frames = {source.dataset_id: load_dataframe(source.path) for source in sources}
    datasets = []
    for source in sources:
        frame = frames[source.dataset_id]
        profile = profile_dataframe(frame)
        datasets.append({
            "dataset_id": source.dataset_id,
            "filename": source.filename,
            "rows": len(frame),
            "columns": len(frame.columns),
            "candidate_keys": [name for name, item in profile["columns"].items() if item["null_count"] == 0 and item["unique_count"] == len(frame)],
            "profile": profile,
            "preview": [{str(column): json_value(value) for column, value in row.items()} for row in frame.head(5).to_dict(orient="records")],
        })
    relationships: list[dict[str, Any]] = []
    for index, left_source in enumerate(sources):
        left = frames[left_source.dataset_id]
        for right_source in sources[index + 1:]:
            right = frames[right_source.dataset_id]
            shared = [str(column) for column in left.columns if column in right.columns and _compatible(left[column], right[column])]
            for key in shared:
                relationships.append(_relationship(left_source, right_source, key, left, right))
    relationships.sort(key=lambda item: (item["blocked"], -item["confidence_score"], item["relationship_id"]))

    # Build a conservative spanning model: only high-confidence, non-many-to-many edges.
    connected = {sources[0].dataset_id}
    proposed: list[dict[str, Any]] = []
    remaining = {source.dataset_id for source in sources[1:]}
    while remaining:
        edge = next((item for item in relationships if item["recommended"] and ((item["left_dataset_id"] in connected and item["right_dataset_id"] in remaining) or (item["right_dataset_id"] in connected and item["left_dataset_id"] in remaining))), None)
        if edge is None:
            break
        if edge["right_dataset_id"] in connected:
            edge = {**edge, "left_dataset_id": edge["right_dataset_id"], "left_filename": edge["right_filename"], "left_key": edge["right_key"], "right_dataset_id": edge["left_dataset_id"], "right_filename": edge["left_filename"], "right_key": edge["left_key"], "cardinality": "many_to_one" if edge["left_unique"] else "one_to_many", "left_unique": edge["right_unique"], "right_unique": edge["left_unique"]}
        proposed.append({**edge, "join_type": "left"})
        connected.add(edge["right_dataset_id"])
        remaining.remove(edge["right_dataset_id"])
    status = "single_table" if len(sources) == 1 else "ready" if not remaining else "needs_review"
    return {"model_status": status, "datasets": datasets, "relationships": relationships, "proposed_joins": proposed, "unconnected_dataset_ids": sorted(remaining)}


def materialize_data_model(sources: list[ModelSource], joins: list[dict[str, Any]], output_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    if len(sources) == 1:
        frame = load_dataframe(sources[0].path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output_path, index=False)
        return output_path, []
    inspection = inspect_data_model(sources)
    allowed = {item["relationship_id"]: item for item in inspection["relationships"] if not item["blocked"]}
    if len(joins) != len(sources) - 1:
        raise DataModelError("The approved model must connect every selected dataset exactly once.")
    frames = {source.dataset_id: load_dataframe(source.path) for source in sources}
    model = frames[sources[0].dataset_id].copy()
    connected = {sources[0].dataset_id}
    audit: list[dict[str, Any]] = []
    for number, requested in enumerate(joins, 1):
        relationship = allowed.get(str(requested.get("relationship_id", "")))
        if relationship is None:
            raise DataModelError("An approved relationship is missing, changed, or unsafe. Inspect the model again.")
        left_id, right_id = relationship["left_dataset_id"], relationship["right_dataset_id"]
        if right_id in connected and left_id not in connected:
            left_id, right_id = right_id, left_id
            left_key, right_key = relationship["right_key"], relationship["left_key"]
        else:
            left_key, right_key = relationship["left_key"], relationship["right_key"]
        if left_id not in connected or right_id in connected:
            raise DataModelError("Approved joins must connect one new table at a time without cycles.")
        right = frames[right_id]
        right_unique = not right[right_key].dropna().duplicated().any()
        left_unique = not model[left_key].dropna().duplicated().any()
        if not right_unique and not left_unique:
            raise DataModelError(f"Both sides repeat '{right_key}'; this many-to-many join is blocked.")
        validation = "many_to_one" if right_unique else "one_to_many"
        cardinality = validation
        rows_before = len(model)
        right_label = next(source.filename for source in sources if source.dataset_id == right_id)
        indicator = f"__join_{number}"
        model = model.merge(right, how="left", left_on=left_key, right_on=right_key, suffixes=("", f"__{Path(right_label).stem}"), validate=validation, indicator=indicator)
        matched = int((model[indicator] == "both").sum())
        unmatched = int((model[indicator] == "left_only").sum())
        model = model.drop(columns=[indicator])
        audit.append({
            "join_id": f"J{number}", "relationship_id": relationship["relationship_id"], "join_type": "left",
            "left_dataset_id": left_id, "right_dataset_id": right_id, "left_key": left_key, "right_key": right_key,
            "cardinality": cardinality, "rows_before": rows_before, "rows_after": len(model),
            "matched_rows": matched, "unmatched_rows": unmatched, "row_multiplier": round(len(model) / max(rows_before, 1), 4),
        })
        connected.add(right_id)
    if connected != {source.dataset_id for source in sources}:
        raise DataModelError("The approved joins do not connect every selected dataset.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model.to_csv(output_path, index=False)
    return output_path, audit
