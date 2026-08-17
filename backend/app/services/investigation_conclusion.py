"""Pure deterministic conclusion compilation for completed KPI investigations.

This module intentionally has no dataframe, SQL, LLM, controller, or verifier
dependency.  It resolves existing state, validates lineage, and emits a bounded
epistemic conclusion without changing the supplied state.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.root_cause_contracts import (
    ConclusionReadinessChecks,
    ConclusionStopDetail,
    ConclusionTargetScope,
    DimensionContributionTest,
    InvestigationConclusion,
    InvestigationEvidenceStrength,
    InvestigationFilter,
    InvestigationPathNode,
    InvestigationState,
    SegmentContribution,
    SingleLevelInvestigationRequest,
)


class ConclusionLineageError(ValueError):
    """Raised when a conclusion cannot be traced to completed state evidence."""


def _nodes(state: InvestigationState) -> tuple[InvestigationPathNode, ...]:
    return tuple(sorted(state.investigation_path, key=lambda item: item.depth))


def _node_by_id(state: InvestigationState) -> dict[str, InvestigationPathNode]:
    return {item.node_id: item for item in state.investigation_path}


def _test_by_id(state: InvestigationState) -> dict[str, DimensionContributionTest]:
    return {item.test_id: item for item in state.tests_executed}


def _source_test_for_selection(
    state: InvestigationState,
    source: InvestigationPathNode | None,
    dimension: str,
    segment: str,
) -> tuple[DimensionContributionTest, SegmentContribution] | None:
    allowed = set(source.test_ids) if source is not None else {
        item.test_id for item in state.tests_executed
    }
    candidates: list[tuple[DimensionContributionTest, SegmentContribution]] = []
    for test in state.tests_executed:
        if test.test_id not in allowed or test.dimension != dimension:
            continue
        for contribution in test.segment_contributions:
            if contribution.segment == segment and contribution.direction == "with_incident":
                candidates.append((test, contribution))
    candidates.sort(key=lambda item: item[0].test_id)
    return candidates[0] if candidates else None


def _resolve_target(
    state: InvestigationState,
) -> tuple[
    ConclusionTargetScope,
    tuple[str, ...],
    InvestigationPathNode | None,
    DimensionContributionTest | None,
    SegmentContribution | None,
    InvestigationEvidenceStrength,
]:
    """Resolve the deepest defensible selected node without inventing scope."""
    ordered = _nodes(state)
    by_id = _node_by_id(state)
    valid_path: list[str] = []
    target_node: InvestigationPathNode | None = None
    target_test: DimensionContributionTest | None = None
    target_contribution: SegmentContribution | None = None

    if ordered:
        root = ordered[0]
        if root.depth != 0 or root.parent_node_id is not None:
            raise ConclusionLineageError("Investigation path must start at one root node")
        valid_path.append(root.node_id)
        previous = root
        for node in ordered[1:]:
            if node.parent_node_id != previous.node_id or node.depth != previous.depth + 1:
                break
            if not node.selected_dimension or not node.selected_segment:
                break
            if not node.filter_path:
                break
            last = node.filter_path[-1]
            if (
                last.dimension != node.selected_dimension
                or last.segment != node.selected_segment
            ):
                break
            resolved = _source_test_for_selection(
                state, previous, node.selected_dimension, node.selected_segment
            )
            if resolved is None:
                break
            test, contribution = resolved
            if test.status != "completed" or not test.reconciles_to_kpi_change:
                break
            if node.evidence_strength not in {"strong", "moderate"}:
                break
            valid_path.append(node.node_id)
            target_node = node
            target_test = test
            target_contribution = contribution
            previous = node

    if target_node is not None and target_test is not None and target_contribution is not None:
        return (
            ConclusionTargetScope(
                source_scope_node_id=str(target_node.parent_node_id),
                target_path_node_id=target_node.node_id,
                filter_path=target_node.filter_path,
                target_dimension=target_node.selected_dimension,
                target_segment=target_node.selected_segment,
            ),
            tuple(valid_path),
            by_id.get(str(target_node.parent_node_id)),
            target_test,
            target_contribution,
            target_node.evidence_strength,
        )

    if state.leading_dimension and state.leading_segment:
        source = by_id.get("IN0")
        resolved = _source_test_for_selection(
            state, source, state.leading_dimension, state.leading_segment
        )
        if resolved is not None:
            test, contribution = resolved
            return (
                ConclusionTargetScope(
                    source_scope_node_id="IN0",
                    filter_path=(
                        InvestigationFilter(
                            dimension=state.leading_dimension,
                            segment=state.leading_segment,
                        ),
                    ),
                    target_dimension=state.leading_dimension,
                    target_segment=state.leading_segment,
                ),
                ("IN0",) if source is not None else (),
                source,
                test,
                contribution,
                state.evidence_strength,
            )

    source = by_id.get("IN0")
    return (
        ConclusionTargetScope(source_scope_node_id="IN0"),
        ("IN0",) if source is not None else (),
        source,
        None,
        None,
        state.evidence_strength,
    )


def _scope_health(state: InvestigationState, source: InvestigationPathNode | None):
    return source.data_health if source is not None else state.data_health


def _scope_tests(
    state: InvestigationState, source: InvestigationPathNode | None
) -> tuple[DimensionContributionTest, ...]:
    if source is None:
        return state.tests_executed
    allowed = set(source.test_ids)
    return tuple(item for item in state.tests_executed if item.test_id in allowed)


def _required_dimensions(
    request: SingleLevelInvestigationRequest,
    source: InvestigationPathNode | None,
) -> set[str]:
    return set(source.remaining_dimensions if source is not None else request.candidate_dimensions)


def _verification_applies(
    state: InvestigationState, target: ConclusionTargetScope
) -> tuple[bool, str | None]:
    planning = state.challenge_planning_record
    if planning is None:
        return False, None
    planned = planning.target
    applies = (
        planned.scope_node_id == target.source_scope_node_id
        and planned.target_dimension == target.target_dimension
        and planned.target_segment == target.target_segment
    )
    return applies, planned.scope_node_id


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _validate_parts(
    *,
    state: InvestigationState,
    target: ConclusionTargetScope,
    path_ids: tuple[str, ...],
    supporting_test_ids: tuple[str, ...],
    supporting_evidence_ids: tuple[str, ...],
    verification_ids: tuple[str, ...],
    verification_target_scope_node_id: str | None,
) -> None:
    nodes = _node_by_id(state)
    tests = _test_by_id(state)
    evidence = {item.evidence_id for item in state.evidence}
    verifications = {item.verification_id: item for item in state.verification_records}

    for index, node_id in enumerate(path_ids):
        if node_id not in nodes:
            raise ConclusionLineageError(f"Conclusion path node {node_id} does not exist")
        if index and nodes[node_id].parent_node_id != path_ids[index - 1]:
            raise ConclusionLineageError("Conclusion path is not a valid parent chain")
        if not set(nodes[node_id].test_ids).issubset(tests):
            raise ConclusionLineageError("Path-node test lineage does not resolve")
        if not set(nodes[node_id].evidence_ids).issubset(evidence):
            raise ConclusionLineageError("Path-node evidence lineage does not resolve")
    if target.target_path_node_id and (
        not path_ids or path_ids[-1] != target.target_path_node_id
    ):
        raise ConclusionLineageError("Conclusion target is not the final path node")
    if target.source_scope_node_id not in nodes and state.investigation_path:
        raise ConclusionLineageError("Conclusion source scope does not exist")
    if not set(supporting_test_ids).issubset(tests):
        raise ConclusionLineageError("Conclusion test reference does not resolve")
    if not set(supporting_evidence_ids).issubset(evidence):
        raise ConclusionLineageError("Conclusion evidence reference does not resolve")
    if target.target_dimension and target.target_segment:
        matching = [
            (test, contribution)
            for test_id in supporting_test_ids
            for test in (tests[test_id],)
            if test.dimension == target.target_dimension
            for contribution in test.segment_contributions
            if contribution.segment == target.target_segment
            and contribution.direction == "with_incident"
        ]
        if not matching:
            raise ConclusionLineageError("Conclusion target does not resolve in supporting tests")
        if not any(test.evidence_id in supporting_evidence_ids for test, _ in matching):
            raise ConclusionLineageError("Conclusion target evidence is not explicitly supported")
    if not set(verification_ids).issubset(verifications):
        raise ConclusionLineageError("Conclusion verification reference does not resolve")
    if verification_target_scope_node_id is not None and verification_target_scope_node_id not in nodes:
        raise ConclusionLineageError("Verification target scope does not resolve")
    for verification_id in verification_ids:
        record = verifications[verification_id]
        if not set(record.source_test_ids).issubset(tests):
            raise ConclusionLineageError("Verification test lineage does not resolve")
        if not set(record.source_evidence_ids).issubset(evidence):
            raise ConclusionLineageError("Verification evidence lineage does not resolve")


def validate_conclusion_lineage(
    conclusion: InvestigationConclusion, state: InvestigationState
) -> None:
    """Validate every conclusion reference against immutable completed state."""
    _validate_parts(
        state=state,
        target=conclusion.target_scope,
        path_ids=conclusion.conclusion_path_node_ids,
        supporting_test_ids=conclusion.supporting_test_ids,
        supporting_evidence_ids=conclusion.supporting_evidence_ids,
        verification_ids=conclusion.verification_ids,
        verification_target_scope_node_id=conclusion.verification_target_scope_node_id,
    )


def compile_investigation_conclusion(
    state: InvestigationState | Mapping[str, object],
    request: SingleLevelInvestigationRequest | Mapping[str, object],
) -> InvestigationConclusion:
    """Compile one bounded conclusion solely from completed investigation state."""
    state = InvestigationState.model_validate(state)
    request = SingleLevelInvestigationRequest.model_validate(request)
    if state.investigation_id != request.investigation_id:
        raise ConclusionLineageError("Request and state investigation IDs differ")
    if state.kpi != request.kpi or (
        state.baseline_period != request.baseline_period
        or state.comparison_period != request.comparison_period
    ):
        raise ConclusionLineageError("Request and state analytical scope differ")

    target, path_ids, source, target_test, contribution, strength = _resolve_target(state)
    health = _scope_health(state, source)
    tests = _scope_tests(state, source)
    required = _required_dimensions(request, source)
    tested = {item.dimension for item in tests if item.status == "completed"}
    exact_safe = not any(
        item.blocking and item.status == "fail" for item in health
    )
    required_tested = required.issubset(tested) and all(
        item.status == "completed" for item in tests
    )
    reconciled = bool(tests) and all(item.reconciles_to_kpi_change for item in tests)
    leader_resolved = target_test is not None and contribution is not None
    conclusion_strength = (
        state.verification_evidence_strength
        if state.verification_status in {"weakened", "abstain"}
        else strength
    )
    evidence_sufficient = leader_resolved and conclusion_strength in {
        "strong",
        "moderate",
    }
    valid_movement = state.net_kpi_movement is not None and abs(state.net_kpi_movement) > request.negligible_parent_movement_tolerance
    verification_required = request.self_falsification_enabled
    verification_completed = bool(state.verification_records) and state.verification_status != "not_run"
    verification_applies, verification_scope = _verification_applies(state, target)
    execution_complete = required_tested and all(
        item.status == "completed" for item in tests
    )

    supporting_test_ids = (target_test.test_id,) if target_test else ()
    supporting_evidence_ids: list[str] = []
    if target_test:
        supporting_evidence_ids.append(target_test.evidence_id)
    if not exact_safe:
        supporting_evidence_ids.extend(
            item.evidence_id for item in health if item.blocking and item.status == "fail"
        )
    verification_ids = tuple(item.verification_id for item in state.verification_records)
    supporting_evidence = _unique(supporting_evidence_ids)
    _validate_parts(
        state=state,
        target=target,
        path_ids=path_ids,
        supporting_test_ids=supporting_test_ids,
        supporting_evidence_ids=supporting_evidence,
        verification_ids=verification_ids,
        verification_target_scope_node_id=verification_scope,
    )

    low_stops = tuple(
        ConclusionStopDetail(
            scope_node_id=node.node_id,
            filter_path=node.filter_path,
            stopping_reason=node.stopping_reason,
        )
        for node in _nodes(state)
        if node.stopping_reason is not None
    )
    downstream_stop = next(
        (
            item
            for item in reversed(low_stops)
            if target.target_path_node_id is not None
            and item.scope_node_id == target.target_path_node_id
        ),
        None,
    )

    caveats: list[str] = []
    result_codes = {item.result_code for item in state.verification_records}
    if "offsets_material" in result_codes or "offsets_caution" in result_codes:
        caveats.append("material_offsets")
    if {
        "leading_segment_remainder_caution",
        "leading_segment_remainder_material",
    } & result_codes:
        caveats.append("leading_segment_remainder")
    if {
        "insufficient_segment_sample",
        "segment_structurally_absent_caution",
        "segment_structurally_absent_material",
        "segment_baseline_unavailable",
    } & result_codes:
        caveats.append("insufficient_segment_reliability")
    if state.verification_status == "competing_explanations":
        caveats.append("competing_decomposition")
    if downstream_stop:
        if downstream_stop.stopping_reason == "maximum_depth_reached":
            caveats.append("maximum_depth_boundary")
        elif downstream_stop.stopping_reason == "scoped_data_quality_failure":
            caveats.append("downstream_scope_data_quality")
        elif downstream_stop.stopping_reason == "reconciliation_failure":
            caveats.append("reconciliation_failure")
        elif downstream_stop.stopping_reason in {
            "insufficient_rows",
            "negligible_parent_movement",
        }:
            caveats.append("insufficient_evidence")
        elif downstream_stop.stopping_reason in {
            "no_aligned_child_contributor",
            "no_material_child_contributor",
        }:
            caveats.append("no_material_driver")
    if any(item.status == "caution" for item in health):
        caveats.append("nonblocking_data_quality")
    if not evidence_sufficient:
        caveats.append("insufficient_evidence")
    if not required_tested:
        caveats.append("incomplete_testing")
    if not reconciled and tests:
        caveats.append("reconciliation_failure")
    if verification_required and not verification_completed:
        caveats.append("verification_not_completed")
    if verification_completed and not verification_applies and leader_resolved:
        caveats.append("robustness_applies_to_upstream_scope_only")

    claim_type: str
    readiness: str
    terminal: str
    next_action: str
    if not exact_safe:
        claim_type = "data_quality_abstention"
        readiness = "not_ready_data_quality"
        terminal = "blocked_by_data_quality"
        next_action = "improve_data_quality"
    elif state.verification_status == "competing_explanations":
        claim_type = "competing_explanations"
        readiness = "not_ready_competing_explanations"
        terminal = "inconclusive"
        next_action = "inspect_competing_explanation"
    elif not reconciled and tests:
        claim_type = "mathematical_observation" if leader_resolved else "inconclusive"
        readiness = "not_ready_reconciliation"
        terminal = "blocked_by_reconciliation"
        next_action = "repair_reconciliation"
    elif not required_tested:
        claim_type = "mathematical_observation" if leader_resolved else "inconclusive"
        readiness = "not_ready_incomplete_testing"
        terminal = "incomplete_testing"
        next_action = "complete_required_testing"
    elif not leader_resolved or not valid_movement:
        claim_type = "inconclusive"
        readiness = "not_ready_insufficient_evidence"
        terminal = "no_material_driver" if valid_movement else "inconclusive"
        next_action = "expand_candidate_dimensions" if valid_movement else "collect_more_data"
    elif not evidence_sufficient or state.verification_status == "weakened":
        claim_type = "mathematical_observation"
        readiness = "not_ready_insufficient_evidence"
        terminal = "inconclusive"
        next_action = "collect_more_data"
    elif verification_required and not verification_completed:
        claim_type = "mathematical_observation"
        readiness = "not_ready_verification_incomplete"
        terminal = "incomplete_testing"
        next_action = "complete_required_testing"
    elif (
        state.verification_status in {
            "robust_no_material_challenge",
            "robust_with_caveats",
        }
        and verification_applies
    ):
        claim_type = "robust_descriptive_explanation"
        readiness = (
            "ready_with_caveats"
            if state.verification_status == "robust_with_caveats" or caveats
            else "ready"
        )
        terminal = "completed_with_caveats" if caveats else "completed"
        next_action = "review_large_offsets" if "material_offsets" in caveats else "none_required"
    else:
        claim_type = "leading_tested_contributor"
        readiness = "ready_with_caveats" if caveats else "ready"
        terminal = "completed_with_caveats" if caveats else "completed"
        next_action = "none_required"

    if downstream_stop:
        stop = downstream_stop.stopping_reason
        if stop == "maximum_depth_reached":
            terminal = "bounded_by_max_depth"
            next_action = "increase_investigation_depth"
        elif stop == "scoped_data_quality_failure":
            terminal = "blocked_by_data_quality"
            next_action = "improve_data_quality"
        elif stop == "reconciliation_failure":
            terminal = "blocked_by_reconciliation"
            next_action = "repair_reconciliation"
        elif stop == "insufficient_rows":
            terminal = "completed_with_caveats"
            next_action = "collect_more_data"
        elif stop in {"no_aligned_child_contributor", "no_material_child_contributor"}:
            terminal = "no_material_driver"

    checks = ConclusionReadinessChecks(
        valid_kpi_movement=valid_movement,
        exact_scope_data_quality_safe=exact_safe,
        required_dimensions_tested=required_tested,
        reconciliation_passed=reconciled,
        leader_resolved=leader_resolved,
        evidence_sufficient=evidence_sufficient,
        verification_required=verification_required,
        verification_completed=verification_completed,
        verification_applies_to_target=verification_applies,
        execution_complete=execution_complete,
        lineage_validated=True,
    )
    conclusion = InvestigationConclusion(
        conclusion_id="ICL1",
        investigation_id=state.investigation_id,
        claim_type=claim_type,
        readiness_status=readiness,
        terminal_category=terminal,
        kpi=state.kpi,
        baseline_period=state.baseline_period,
        comparison_period=state.comparison_period,
        target_scope=target,
        conclusion_path_node_ids=path_ids,
        leading_dimension=target.target_dimension,
        leading_segment=target.target_segment,
        signed_contribution=contribution.signed_change if contribution else None,
        contribution_to_net_change_pct=(
            contribution.contribution_to_net_change_pct if contribution else None
        ),
        evidence_strength=conclusion_strength,
        robustness_status=state.verification_status,
        verification_target_scope_node_id=verification_scope,
        supporting_test_ids=supporting_test_ids,
        supporting_evidence_ids=supporting_evidence,
        verification_ids=verification_ids,
        caveat_codes=_unique(caveats),
        source_stopping_reason=state.stopping_reason,
        low_level_stops=low_stops,
        readiness_checks=checks,
        recommended_next_action=next_action,
    )
    validate_conclusion_lineage(conclusion, state)
    return conclusion
