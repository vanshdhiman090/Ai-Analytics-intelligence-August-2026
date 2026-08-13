from pathlib import Path

import pandas as pd
import pytest

from app.services.data_model import DataModelError, ModelSource, inspect_data_model, materialize_data_model


def source(tmp_path: Path, dataset_id: str, filename: str, frame: pd.DataFrame) -> ModelSource:
    path = tmp_path / filename
    frame.to_csv(path, index=False)
    return ModelSource(dataset_id=dataset_id, filename=filename, path=path)


def test_detects_and_materializes_safe_multi_file_model(tmp_path: Path):
    orders = source(tmp_path, "orders", "orders.csv", pd.DataFrame({"order_id": [1, 2, 3], "customer_id": [10, 10, 20], "amount": [25, 40, 15]}))
    customers = source(tmp_path, "customers", "customers.csv", pd.DataFrame({"customer_id": [10, 20], "segment": ["SMB", "Enterprise"]}))
    model = inspect_data_model([orders, customers])

    assert model["model_status"] == "ready"
    assert len(model["proposed_joins"]) == 1
    relationship = model["proposed_joins"][0]
    assert relationship["cardinality"] == "many_to_one"
    assert relationship["left_match_rate"] == 1
    assert relationship["right_match_rate"] == 1

    output, audit = materialize_data_model([orders, customers], [{"relationship_id": relationship["relationship_id"]}], tmp_path / "model.csv")
    result = pd.read_csv(output)
    assert len(result) == 3
    assert result["segment"].tolist() == ["SMB", "SMB", "Enterprise"]
    assert audit[0]["row_multiplier"] == 1
    assert audit[0]["unmatched_rows"] == 0


def test_blocks_many_to_many_relationship(tmp_path: Path):
    left = source(tmp_path, "left", "left.csv", pd.DataFrame({"customer_id": [1, 1], "value": [2, 3]}))
    right = source(tmp_path, "right", "right.csv", pd.DataFrame({"customer_id": [1, 1], "label": ["a", "b"]}))
    model = inspect_data_model([left, right])
    relationship = model["relationships"][0]
    assert relationship["blocked"] is True
    assert relationship["cardinality"] == "many_to_many"
    assert model["model_status"] == "needs_review"
    with pytest.raises(DataModelError, match="unsafe"):
        materialize_data_model([left, right], [{"relationship_id": relationship["relationship_id"]}], tmp_path / "bad.csv")


def test_reports_unmatched_keys_without_dropping_left_rows(tmp_path: Path):
    orders = source(tmp_path, "orders", "orders.csv", pd.DataFrame({"customer_id": [10, 30], "amount": [25, 50]}))
    customers = source(tmp_path, "customers", "customers.csv", pd.DataFrame({"customer_id": [10, 20], "segment": ["SMB", "Enterprise"]}))
    relationship = inspect_data_model([orders, customers])["proposed_joins"][0]
    output, audit = materialize_data_model([orders, customers], [{"relationship_id": relationship["relationship_id"]}], tmp_path / "model.csv")
    assert len(pd.read_csv(output)) == 2
    assert audit[0]["unmatched_rows"] == 1
