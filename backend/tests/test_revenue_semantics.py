import pytest
from pydantic import ValidationError

from app.domain.revenue_semantics import (
    ColumnBinding,
    CurrencyPolicy,
    RevenueFieldBindings,
    RevenueMetricDefinition,
    RevenueSemanticError,
    RevenueSemanticLayer,
    build_revenue_semantic_context,
    canonical_revenue_metric,
    infer_revenue_bindings,
)


def binding(column: str, semantic_type: str, source_id: str = "orders") -> ColumnBinding:
    return ColumnBinding(source_id=source_id, column=column, semantic_type=semantic_type)


def required_bindings(**extra) -> RevenueFieldBindings:
    values = {
        "net_revenue": binding("net_revenue", "numeric"),
        "order_id": binding("order_id", "identifier"),
        "order_status": binding("status", "categorical"),
        "occurred_at": binding("completed_at", "datetime"),
    }
    values.update(extra)
    return RevenueFieldBindings(**values)


def layer(bindings: RevenueFieldBindings | None = None) -> RevenueSemanticLayer:
    return RevenueSemanticLayer(
        metric=canonical_revenue_metric(reporting_currency="EUR", timezone="Europe/Berlin"),
        bindings=bindings or required_bindings(),
    )


def test_canonical_metric_locks_revenue_definition_and_business_policies():
    metric = canonical_revenue_metric(reporting_currency="eur", timezone="Europe/Berlin")

    assert metric.expression == "SUM(net_revenue)"
    assert metric.grain == "order"
    assert metric.included_order_statuses == ("completed",)
    assert metric.excluded_order_statuses == ("cancelled",)
    assert metric.refund_policy.treatment == "net_revenue_is_post_refund"
    assert metric.currency_policy.reporting_currency == "EUR"
    assert metric.default_comparison in metric.allowed_comparisons


def test_metric_rejects_ambiguous_status_policy_and_invalid_timezone():
    with pytest.raises(ValidationError, match="both included and excluded"):
        RevenueMetricDefinition(
            currency_policy=CurrencyPolicy(mode="single_currency", reporting_currency="EUR"),
            timezone="Europe/Berlin",
            included_order_statuses=("Completed",),
            excluded_order_statuses=("completed",),
        )

    with pytest.raises(ValidationError, match="valid IANA timezone"):
        canonical_revenue_metric(reporting_currency="EUR", timezone="Berlin-ish")


def test_bindings_reject_wrong_semantic_type_and_cross_source_order_fields():
    with pytest.raises(ValidationError, match="net_revenue requires"):
        required_bindings(net_revenue=binding("net_revenue", "text"))

    with pytest.raises(ValidationError, match="same source"):
        required_bindings(order_id=binding("order_id", "identifier", "other_orders"))


def test_base_resolution_exposes_only_orders_times_aov_branch():
    resolution = layer().resolve(
        {"orders": {"net_revenue", "order_id", "status", "completed_at"}}
    )

    assert [item.branch_id for item in resolution.measurable_branches] == [
        "revenue_orders_aov"
    ]
    assert {item.branch_id for item in resolution.unavailable_branches} == {
        "revenue_gross_discount_refund",
        "orders_sessions_conversion",
    }
    assert any("post-refund" in guard for guard in resolution.execution_guards)


def test_optional_fields_activate_only_exactly_measurable_driver_branches():
    bindings = required_bindings(
        gross_revenue=binding("gross_revenue", "numeric"),
        discount_amount=binding("discount_amount", "numeric"),
        refund_amount=binding("refund_amount", "numeric"),
        session_id=binding("session_id", "identifier", "sessions"),
        converted_flag=binding("converted", "boolean", "sessions"),
    )
    resolution = layer(bindings).resolve(
        {
            "orders": {
                "net_revenue",
                "order_id",
                "status",
                "completed_at",
                "gross_revenue",
                "discount_amount",
                "refund_amount",
            },
            "sessions": {"session_id", "converted"},
        }
    )

    assert [item.branch_id for item in resolution.measurable_branches] == [
        "revenue_orders_aov",
        "revenue_gross_discount_refund",
        "orders_sessions_conversion",
    ]
    assert resolution.unavailable_branches == ()


def test_resolution_fails_closed_for_a_binding_not_present_in_schema_profile():
    with pytest.raises(RevenueSemanticError, match="order_status -> orders.status"):
        layer().resolve({"orders": {"net_revenue", "order_id", "completed_at"}})


def test_resolution_round_trips_as_session_safe_json_without_raw_rows():
    resolution = layer().resolve(
        {"orders": {"net_revenue", "order_id", "status", "completed_at"}}
    )

    payload = resolution.model_dump(mode="json")
    restored = type(resolution).model_validate(payload)

    assert restored == resolution
    assert "measurable_branches" in payload
    assert "rows" not in str(payload).lower()


def schema_profile(**columns):
    return {"columns": columns}


def test_exact_alias_inference_builds_json_ready_semantic_context():
    metric = canonical_revenue_metric(reporting_currency="EUR", timezone="Europe/Berlin")
    profile = schema_profile(
        **{
            "Net Revenue": {"semantic_type": "numeric"},
            "Order ID": {"semantic_type": "categorical"},
            "Order Status": {"semantic_type": "categorical"},
            "Completed At": {"semantic_type": "datetime"},
        }
    )

    context = build_revenue_semantic_context(metric, {"uploaded_orders": profile})
    payload = context.model_dump(mode="json")

    assert context.inference.status == "ready"
    assert context.resolution is not None
    assert context.resolution.measurable_branches[0].branch_id == "revenue_orders_aov"
    assert payload["inference"]["bindings"]["net_revenue"]["column"] == "Net Revenue"


def test_inference_abstains_when_a_required_field_is_ambiguous():
    inference = infer_revenue_bindings(
        {
            "orders": schema_profile(
                net_revenue={"semantic_type": "numeric"},
                revenue_net={"semantic_type": "numeric"},
                order_id={"semantic_type": "identifier"},
                order_status={"semantic_type": "categorical"},
                order_date={"semantic_type": "datetime"},
            )
        }
    )

    assert inference.status == "abstained"
    assert inference.bindings is None
    issue = next(item for item in inference.issues if item.canonical_field == "net_revenue")
    assert issue.kind == "ambiguous"
    assert issue.candidates == ("orders.net_revenue", "orders.revenue_net")


def test_inference_does_not_guess_that_generic_revenue_means_net_revenue():
    inference = infer_revenue_bindings(
        {
            "orders": schema_profile(
                revenue={"semantic_type": "numeric"},
                order_id={"semantic_type": "identifier"},
                order_status={"semantic_type": "categorical"},
                order_date={"semantic_type": "datetime"},
            )
        }
    )

    assert inference.status == "abstained"
    assert any(
        item.canonical_field == "net_revenue" and item.kind == "missing"
        for item in inference.issues
    )


def test_optional_ambiguous_field_is_omitted_without_blocking_base_revenue():
    inference = infer_revenue_bindings(
        {
            "orders": schema_profile(
                net_revenue={"semantic_type": "numeric"},
                order_id={"semantic_type": "identifier"},
                order_status={"semantic_type": "categorical"},
                order_date={"semantic_type": "datetime"},
                gross_revenue={"semantic_type": "numeric"},
                gross_sales={"semantic_type": "numeric"},
            )
        }
    )

    assert inference.status == "ready"
    assert inference.bindings is not None
    assert inference.bindings.gross_revenue is None
    assert any(
        item.canonical_field == "gross_revenue" and item.kind == "ambiguous"
        for item in inference.issues
    )
