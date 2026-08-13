"""Canonical Revenue semantics for evidence-first KPI investigations.

This module deliberately contains no orchestration or persistence logic.  The
contracts are JSON serializable, so a validated semantic layer or resolution
can be placed in a session ``run_input``/``result_summary`` without teaching
the session API about Revenue.

The V0 contract is intentionally narrow: Revenue is the sum of net revenue at
order grain after the documented order-status policy has been applied.  A
driver branch is exposed only when every field needed for an exact identity is
bound to an available source column.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SemanticType = Literal[
    "numeric",
    "datetime",
    "boolean",
    "categorical",
    "text",
    "identifier",
]
ComparisonPolicy = Literal[
    "previous_comparable_period",
    "same_weekday_previous_week",
    "year_over_year",
    "rolling_4_week_average",
]
CanonicalRevenueField = Literal[
    "net_revenue",
    "order_id",
    "order_status",
    "occurred_at",
    "currency",
    "gross_revenue",
    "discount_amount",
    "refund_amount",
    "session_id",
    "converted_flag",
]
ComputationCapability = Literal[
    "filtered_sum",
    "filtered_count_distinct",
    "ratio_of_aggregates",
    "difference_of_aggregates",
]


class RevenueSemanticError(ValueError):
    """Raised when a Revenue contract cannot be measured from supplied data."""


class StrictContract(BaseModel):
    """Reject undeclared semantics instead of silently accepting misspellings."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnBinding(StrictContract):
    """A canonical field's explicit physical location and expected type."""

    source_id: str = Field(min_length=1, max_length=200)
    column: str = Field(min_length=1, max_length=200)
    semantic_type: SemanticType

    @field_validator("source_id", "column")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class RefundPolicy(StrictContract):
    """V0 keeps refund treatment fixed so Revenue cannot drift between runs."""

    treatment: Literal["net_revenue_is_post_refund"] = "net_revenue_is_post_refund"
    description: Literal[
        "Refunds are already reflected in net_revenue; do not subtract them again."
    ] = "Refunds are already reflected in net_revenue; do not subtract them again."


class CurrencyPolicy(StrictContract):
    """How monetary values become safe to aggregate."""

    mode: Literal["single_currency", "preconverted_to_reporting_currency"]
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("reporting_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class RevenueMetricDefinition(StrictContract):
    """The one canonical Revenue definition used by V0 investigations."""

    metric_id: Literal["revenue"] = "revenue"
    contract_version: Literal["0.1.0"] = "0.1.0"
    label: Literal["Revenue"] = "Revenue"
    expression: Literal["SUM(net_revenue)"] = "SUM(net_revenue)"
    grain: Literal["order"] = "order"
    aggregation: Literal["sum"] = "sum"
    included_order_statuses: tuple[str, ...] = Field(default=("completed",), min_length=1)
    excluded_order_statuses: tuple[str, ...] = ("cancelled",)
    refund_policy: RefundPolicy = Field(default_factory=RefundPolicy)
    currency_policy: CurrencyPolicy
    timezone: str = Field(min_length=1, description="IANA timezone used for period boundaries.")
    default_comparison: ComparisonPolicy = "previous_comparable_period"
    allowed_comparisons: tuple[ComparisonPolicy, ...] = (
        "previous_comparable_period",
        "same_weekday_previous_week",
        "year_over_year",
        "rolling_4_week_average",
    )

    @field_validator("included_order_statuses", "excluded_order_statuses", mode="before")
    @classmethod
    def normalize_statuses(cls, values: Collection[str]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(value).strip().lower() for value in values if str(value).strip()))
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_iana_timezone(cls, value: str) -> str:
        cleaned = value.strip()
        try:
            ZoneInfo(cleaned)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return cleaned

    @model_validator(mode="after")
    def validate_metric_policy(self):
        if not self.included_order_statuses:
            raise ValueError("at least one included order status is required")
        overlap = set(self.included_order_statuses) & set(self.excluded_order_statuses)
        if overlap:
            raise ValueError(f"order statuses cannot be both included and excluded: {sorted(overlap)}")
        if self.default_comparison not in self.allowed_comparisons:
            raise ValueError("default comparison must be present in allowed comparisons")
        return self


_ALLOWED_TYPES: dict[CanonicalRevenueField, frozenset[SemanticType]] = {
    "net_revenue": frozenset({"numeric"}),
    "order_id": frozenset({"identifier", "categorical", "text", "numeric"}),
    "order_status": frozenset({"categorical", "text"}),
    "occurred_at": frozenset({"datetime"}),
    "currency": frozenset({"categorical", "text"}),
    "gross_revenue": frozenset({"numeric"}),
    "discount_amount": frozenset({"numeric"}),
    "refund_amount": frozenset({"numeric"}),
    "session_id": frozenset({"identifier", "categorical", "text", "numeric"}),
    "converted_flag": frozenset({"boolean", "numeric"}),
}


class RevenueFieldBindings(StrictContract):
    """Physical bindings required to apply the canonical Revenue contract."""

    net_revenue: ColumnBinding
    order_id: ColumnBinding
    order_status: ColumnBinding
    occurred_at: ColumnBinding
    currency: ColumnBinding | None = None
    gross_revenue: ColumnBinding | None = None
    discount_amount: ColumnBinding | None = None
    refund_amount: ColumnBinding | None = None
    session_id: ColumnBinding | None = None
    converted_flag: ColumnBinding | None = None

    @model_validator(mode="after")
    def validate_bindings(self):
        for canonical_field in self.__class__.model_fields:
            binding = getattr(self, canonical_field)
            if binding is None:
                continue
            allowed = _ALLOWED_TYPES[canonical_field]
            if binding.semantic_type not in allowed:
                raise ValueError(
                    f"{canonical_field} requires one of {sorted(allowed)}, got {binding.semantic_type}"
                )

        order_source = self.net_revenue.source_id
        order_bindings = (
            self.order_id,
            self.order_status,
            self.occurred_at,
            self.currency,
            self.gross_revenue,
            self.discount_amount,
            self.refund_amount,
        )
        if any(binding is not None and binding.source_id != order_source for binding in order_bindings):
            raise ValueError("all order-grain Revenue fields must use the same source")

        if (self.session_id is None) != (self.converted_flag is None):
            raise ValueError("session_id and converted_flag must be bound together")
        if self.session_id and self.session_id.source_id != self.converted_flag.source_id:
            raise ValueError("session_id and converted_flag must use the same session-grain source")
        return self

    def bound_fields(self) -> dict[CanonicalRevenueField, ColumnBinding]:
        return {
            field: binding
            for field in self.__class__.model_fields
            if (binding := getattr(self, field)) is not None
        }


class DriverBranch(StrictContract):
    """An exact, testable mathematical branch in the Revenue driver tree."""

    branch_id: Literal[
        "revenue_orders_aov",
        "revenue_gross_discount_refund",
        "orders_sessions_conversion",
    ]
    output_metric: str
    equation: str
    required_fields: tuple[CanonicalRevenueField, ...]
    required_capabilities: tuple[ComputationCapability, ...]
    interpretation: str


REVENUE_DRIVER_BRANCHES: tuple[DriverBranch, ...] = (
    DriverBranch(
        branch_id="revenue_orders_aov",
        output_metric="revenue",
        equation="revenue = order_count × average_order_value",
        required_fields=("net_revenue", "order_id", "order_status", "occurred_at"),
        required_capabilities=("filtered_sum", "filtered_count_distinct", "ratio_of_aggregates"),
        interpretation="Separates order-volume movement from average-order-value movement.",
    ),
    DriverBranch(
        branch_id="revenue_gross_discount_refund",
        output_metric="net_revenue",
        equation="net_revenue = gross_revenue - discount_amount - refund_amount",
        required_fields=("net_revenue", "gross_revenue", "discount_amount", "refund_amount"),
        required_capabilities=("filtered_sum", "difference_of_aggregates"),
        interpretation="Reconciles net Revenue movement to gross sales, discounts, and refunds.",
    ),
    DriverBranch(
        branch_id="orders_sessions_conversion",
        output_metric="order_count",
        equation="order_count = session_count × conversion_rate",
        required_fields=("session_id", "converted_flag"),
        required_capabilities=("filtered_count_distinct", "ratio_of_aggregates"),
        interpretation="Separates traffic volume from observed session-to-order conversion.",
    ),
)


class UnavailableDriverBranch(StrictContract):
    branch_id: str
    missing_bindings: tuple[CanonicalRevenueField, ...]
    reason: Literal["required_fields_not_bound"] = "required_fields_not_bound"


class RevenueSemanticResolution(StrictContract):
    """Session-safe proof of which Revenue branches the supplied data supports."""

    contract_version: Literal["0.1.0"] = "0.1.0"
    metric: RevenueMetricDefinition
    bindings: RevenueFieldBindings
    measurable_branches: tuple[DriverBranch, ...]
    unavailable_branches: tuple[UnavailableDriverBranch, ...]
    execution_guards: tuple[str, ...]


class RevenueSemanticLayer(StrictContract):
    """Canonical Revenue metric plus explicit physical bindings."""

    metric: RevenueMetricDefinition
    bindings: RevenueFieldBindings

    def resolve(
        self,
        available_columns_by_source: Mapping[str, Collection[str]],
    ) -> RevenueSemanticResolution:
        """Validate bindings and return only driver branches measurable from data.

        ``available_columns_by_source`` should come from the dataset schema
        profile.  It deliberately contains column names only, never raw rows.
        """

        available = {
            str(source_id): {str(column) for column in columns}
            for source_id, columns in available_columns_by_source.items()
        }
        missing_columns = [
            f"{canonical_field} -> {binding.source_id}.{binding.column}"
            for canonical_field, binding in self.bindings.bound_fields().items()
            if binding.source_id not in available or binding.column not in available[binding.source_id]
        ]
        if missing_columns:
            raise RevenueSemanticError(
                "Revenue bindings reference unavailable source columns: " + ", ".join(missing_columns)
            )

        bound_fields = set(self.bindings.bound_fields())
        measurable: list[DriverBranch] = []
        unavailable: list[UnavailableDriverBranch] = []
        for branch in REVENUE_DRIVER_BRANCHES:
            missing = tuple(field for field in branch.required_fields if field not in bound_fields)
            if missing:
                unavailable.append(
                    UnavailableDriverBranch(branch_id=branch.branch_id, missing_bindings=missing)
                )
            else:
                measurable.append(branch)

        guards = [
            "Filter order_status to the included statuses before aggregating Revenue.",
            "Exclude documented excluded order statuses before aggregating Revenue.",
            "Treat net_revenue as post-refund; never subtract refunds twice.",
            f"Aggregate monetary values only in {self.metric.currency_policy.reporting_currency} under the declared currency policy.",
            f"Build period boundaries in {self.metric.timezone}.",
            "Do not treat a mathematical driver as a proven causal mechanism.",
        ]
        if self.metric.currency_policy.mode == "single_currency" and self.bindings.currency is None:
            guards.append(
                "The reporting currency is a declared source-level constant because no row-level currency field is bound."
            )

        return RevenueSemanticResolution(
            metric=self.metric,
            bindings=self.bindings,
            measurable_branches=tuple(measurable),
            unavailable_branches=tuple(unavailable),
            execution_guards=tuple(guards),
        )


class BindingInferenceIssue(StrictContract):
    """Why inference declined to bind a canonical Revenue field."""

    canonical_field: CanonicalRevenueField
    kind: Literal["missing", "ambiguous", "type_mismatch", "source_conflict"]
    candidates: tuple[str, ...] = ()
    explanation: str


class RevenueBindingInference(StrictContract):
    """Auditable output of conservative schema-to-semantics inference."""

    status: Literal["ready", "abstained"]
    bindings: RevenueFieldBindings | None = None
    inferred_fields: dict[CanonicalRevenueField, ColumnBinding] = Field(default_factory=dict)
    issues: tuple[BindingInferenceIssue, ...] = ()

    @model_validator(mode="after")
    def validate_status(self):
        if self.status == "ready" and self.bindings is None:
            raise ValueError("ready inference requires validated bindings")
        if self.status == "abstained" and self.bindings is not None:
            raise ValueError("abstained inference cannot publish validated bindings")
        return self


class RevenueSemanticContext(StrictContract):
    """JSON-ready context that an API/session/agent can consume safely."""

    contract_version: Literal["0.1.0"] = "0.1.0"
    metric: RevenueMetricDefinition
    inference: RevenueBindingInference
    resolution: RevenueSemanticResolution | None = None

    @model_validator(mode="after")
    def validate_resolution_state(self):
        if self.inference.status == "abstained" and self.resolution is not None:
            raise ValueError("an abstained inference cannot have a semantic resolution")
        if self.inference.status == "ready" and self.resolution is None:
            raise ValueError("ready inference requires a semantic resolution")
        return self


# Aliases are intentionally short and explicit. Fuzzy similarity is forbidden:
# a plausible name is not enough evidence to redefine a business metric.
_EXACT_FIELD_ALIASES: dict[CanonicalRevenueField, frozenset[str]] = {
    "net_revenue": frozenset({"net_revenue", "revenue_net"}),
    "order_id": frozenset({"order_id", "orderid"}),
    "order_status": frozenset({"order_status", "status"}),
    "occurred_at": frozenset({"order_completed_at", "completed_at", "order_date"}),
    "currency": frozenset({"currency", "currency_code"}),
    "gross_revenue": frozenset({"gross_revenue", "gross_sales"}),
    "discount_amount": frozenset({"discount_amount", "discount_value"}),
    "refund_amount": frozenset({"refund_amount", "refunded_amount"}),
    "session_id": frozenset({"session_id", "sessionid"}),
    "converted_flag": frozenset({"converted_flag", "is_converted", "converted"}),
}
_REQUIRED_REVENUE_FIELDS: tuple[CanonicalRevenueField, ...] = (
    "net_revenue",
    "order_id",
    "order_status",
    "occurred_at",
)


def _normalize_column_name(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.strip().lower())).strip("_")


def _profile_columns(profile: Mapping[str, object]) -> Mapping[str, object]:
    nested = profile.get("columns")
    return nested if isinstance(nested, Mapping) else profile


def _profile_semantic_type(detail: object) -> str | None:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, Mapping):
        value = detail.get("semantic_type")
        return str(value) if value is not None else None
    return None


def infer_revenue_bindings(
    source_profiles: Mapping[str, Mapping[str, object]],
) -> RevenueBindingInference:
    """Infer bindings only from explicit aliases and compatible profile types.

    The function never chooses between multiple matches, never uses fuzzy name
    similarity, and never infers a field without a declared semantic type.  It
    therefore produces a useful partial audit even when it must abstain.
    """

    candidates_by_field: dict[CanonicalRevenueField, list[tuple[str, str, str | None]]] = {
        field: [] for field in _EXACT_FIELD_ALIASES
    }
    for source_id, profile in source_profiles.items():
        for column, detail in _profile_columns(profile).items():
            normalized = _normalize_column_name(str(column))
            for canonical_field, aliases in _EXACT_FIELD_ALIASES.items():
                if normalized in aliases:
                    candidates_by_field[canonical_field].append(
                        (str(source_id), str(column), _profile_semantic_type(detail))
                    )

    inferred: dict[CanonicalRevenueField, ColumnBinding] = {}
    issues: list[BindingInferenceIssue] = []
    for canonical_field, candidates in candidates_by_field.items():
        required = canonical_field in _REQUIRED_REVENUE_FIELDS
        candidate_labels = tuple(f"{source}.{column}" for source, column, _ in candidates)
        if not candidates:
            if required:
                issues.append(
                    BindingInferenceIssue(
                        canonical_field=canonical_field,
                        kind="missing",
                        explanation="No exact approved alias was present in the schema profile.",
                    )
                )
            continue
        if len(candidates) > 1:
            issues.append(
                BindingInferenceIssue(
                    canonical_field=canonical_field,
                    kind="ambiguous",
                    candidates=candidate_labels,
                    explanation="Multiple exact aliases matched; human confirmation is required.",
                )
            )
            continue

        source_id, column, semantic_type = candidates[0]
        if semantic_type not in _ALLOWED_TYPES[canonical_field]:
            issues.append(
                BindingInferenceIssue(
                    canonical_field=canonical_field,
                    kind="type_mismatch",
                    candidates=candidate_labels,
                    explanation=(
                        f"Profile type {semantic_type or 'unknown'} is incompatible with "
                        f"the canonical {canonical_field} field."
                    ),
                )
            )
            continue
        inferred[canonical_field] = ColumnBinding(
            source_id=source_id,
            column=column,
            semantic_type=semantic_type,
        )

    blocking_fields = {
        issue.canonical_field
        for issue in issues
        if issue.canonical_field in _REQUIRED_REVENUE_FIELDS
    }
    if not blocking_fields:
        required_sources = {inferred[field].source_id for field in _REQUIRED_REVENUE_FIELDS}
        if len(required_sources) != 1:
            for field in _REQUIRED_REVENUE_FIELDS:
                issues.append(
                    BindingInferenceIssue(
                        canonical_field=field,
                        kind="source_conflict",
                        candidates=(
                            f"{inferred[field].source_id}.{inferred[field].column}",
                        ),
                        explanation="Required order-grain fields do not share one source.",
                    )
                )
            blocking_fields.update(_REQUIRED_REVENUE_FIELDS)

    if blocking_fields:
        return RevenueBindingInference(
            status="abstained",
            inferred_fields=inferred,
            issues=tuple(issues),
        )

    # Optional ambiguous/incompatible fields stay unbound. This preserves the
    # valid base Revenue definition while suppressing unsupported driver branches.
    try:
        bindings = RevenueFieldBindings(**inferred)
    except ValueError as exc:
        return RevenueBindingInference(
            status="abstained",
            inferred_fields=inferred,
            issues=tuple(issues)
            + (
                BindingInferenceIssue(
                    canonical_field="net_revenue",
                    kind="source_conflict",
                    explanation=str(exc),
                ),
            ),
        )
    return RevenueBindingInference(
        status="ready",
        bindings=bindings,
        inferred_fields=inferred,
        issues=tuple(issues),
    )


def build_revenue_semantic_context(
    metric: RevenueMetricDefinition,
    source_profiles: Mapping[str, Mapping[str, object]],
) -> RevenueSemanticContext:
    """Build JSON-ready semantic context, abstaining on uncertain required fields."""

    inference = infer_revenue_bindings(source_profiles)
    if inference.status == "abstained" or inference.bindings is None:
        return RevenueSemanticContext(metric=metric, inference=inference)
    available_columns = {
        str(source_id): tuple(str(column) for column in _profile_columns(profile))
        for source_id, profile in source_profiles.items()
    }
    resolution = RevenueSemanticLayer(metric=metric, bindings=inference.bindings).resolve(
        available_columns
    )
    return RevenueSemanticContext(metric=metric, inference=inference, resolution=resolution)


def canonical_revenue_metric(
    *,
    reporting_currency: str,
    timezone: str,
    currency_mode: Literal["single_currency", "preconverted_to_reporting_currency"] = "single_currency",
) -> RevenueMetricDefinition:
    """Create the locked V0 Revenue definition with explicit local policies."""

    return RevenueMetricDefinition(
        currency_policy=CurrencyPolicy(
            mode=currency_mode,
            reporting_currency=reporting_currency,
        ),
        timezone=timezone,
    )
