import pandas as pd

from app.services.tabular import classify_numeric_role, profile_dataframe


def coffee_shop_frame(rows: int = 200) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transaction_id": list(range(1, rows + 1)),
            "store_id": [i % 5 for i in range(rows)],
            "product_id": [i % 40 for i in range(rows)],
            "Hour": [i % 24 for i in range(rows)],
            "Month": [i % 12 + 1 for i in range(rows)],
            "Day of Week": [i % 7 for i in range(rows)],
            "Rating": [i % 5 + 1 for i in range(rows)],
            "is_member": [i % 2 for i in range(rows)],
            "Total Bill": [round(3.5 + (i % 37) * 0.25, 2) for i in range(rows)],
            "Unit Price": [round(2.0 + (i % 23) * 0.1, 2) for i in range(rows)],
            "Category": (["Coffee", "Tea", "Pastry", "Snack"] * (rows // 4))[:rows],
        }
    )


def test_identifier_columns_are_excluded_from_quantity_role():
    profile = profile_dataframe(coffee_shop_frame())
    columns = profile["columns"]
    assert columns["transaction_id"]["numeric_role"] == "identifier"
    assert columns["store_id"]["numeric_role"] == "identifier"
    assert columns["product_id"]["numeric_role"] == "identifier"


def test_calendar_position_columns_are_classified_cyclical():
    profile = profile_dataframe(coffee_shop_frame())
    columns = profile["columns"]
    assert columns["Hour"]["numeric_role"] == "cyclical"
    assert columns["Month"]["numeric_role"] == "cyclical"
    assert columns["Day of Week"]["numeric_role"] == "cyclical"


def test_low_cardinality_non_calendar_columns_are_classified_discrete_scale():
    profile = profile_dataframe(coffee_shop_frame())
    columns = profile["columns"]
    assert columns["Rating"]["numeric_role"] == "discrete_scale"
    assert columns["is_member"]["numeric_role"] == "discrete_scale"


def test_continuous_business_quantities_are_classified_quantity():
    profile = profile_dataframe(coffee_shop_frame())
    columns = profile["columns"]
    assert columns["Total Bill"]["numeric_role"] == "quantity"
    assert columns["Unit Price"]["numeric_role"] == "quantity"


def test_non_numeric_columns_have_no_numeric_role():
    profile = profile_dataframe(coffee_shop_frame())
    assert profile["columns"]["Category"]["numeric_role"] is None


def test_a_named_calendar_column_with_too_many_distinct_values_is_not_cyclical():
    # 20 distinct "Month" values does not fit a 12-month calendar (and stays
    # under the identifier uniqueness ratio), so this must fall through past
    # both the cyclical and discrete_scale checks to quantity, not be
    # misread as cyclical just because the name matches.
    rows = 200
    frame = pd.DataFrame({"Month": [i % 20 for i in range(rows)]})
    role = classify_numeric_role(frame["Month"], "Month", len(frame))
    assert role == "quantity"
