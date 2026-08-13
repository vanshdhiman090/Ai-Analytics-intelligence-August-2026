from app.agent.share_node import chart_metadata, render_evidence_chart


def evidence(kind, rows, columns):
    return {
        "evidence_id": "E1",
        "kind": kind,
        "title": "Validated evidence view",
        "rows": rows,
        "columns": columns,
        "population": "120 retained rows",
        "method": "Controlled descriptive calculation",
    }


def test_long_rankings_render_as_bounded_executive_chart(tmp_path):
    item = evidence(
        "grouped_aggregate",
        [{"segment": f"Segment {index}", "value": index * 1_000} for index in range(1, 21)],
        ["segment", "value"],
    )
    output = tmp_path / "ranking.png"

    assert render_evidence_chart(item, output) is True
    assert output.stat().st_size > 10_000
    assert chart_metadata(item)["chart_type"] == "ranked horizontal bar"


def test_distribution_quantiles_render_as_range_not_fake_trend(tmp_path):
    item = evidence(
        "distribution",
        [
            {"quantile": 0.0, "value": 10},
            {"quantile": 0.25, "value": 20},
            {"quantile": 0.5, "value": 30},
            {"quantile": 0.75, "value": 45},
            {"quantile": 1.0, "value": 90},
        ],
        ["quantile", "value"],
    )
    output = tmp_path / "distribution.png"

    assert render_evidence_chart(item, output) is True
    assert output.stat().st_size > 10_000
    assert chart_metadata(item)["chart_type"] == "quantile range"


def test_short_time_series_uses_period_bars(tmp_path):
    item = evidence(
        "trend",
        [{"period": f"Q{index}", "value": index * 12} for index in range(1, 5)],
        ["period", "value"],
    )

    assert chart_metadata(item)["chart_type"] == "period bar"
    assert render_evidence_chart(item, tmp_path / "periods.png") is True


def test_advanced_evidence_kinds_render(tmp_path):
    ratio = evidence("kpi_ratio", [{"channel":"A","ratio":20,"numerator":30,"denominator":150}], ["channel","ratio"])
    ratio["diagnostics"] = {"scale":100}
    comparison = evidence("statistical_comparison", [{"baseline_group":"A","comparison_group":"B","baseline_mean":10,"comparison_mean":15,"cohens_d":.8,"permutation_p_value":.02}], ["baseline_group","comparison_group","baseline_mean","comparison_mean"])
    change = evidence("segment_change", [{"segment":"A","absolute_change":50},{"segment":"B","absolute_change":-20}], ["segment","absolute_change"])
    assert render_evidence_chart(ratio, tmp_path / "ratio.png") is True
    assert render_evidence_chart(comparison, tmp_path / "comparison.png") is True
    assert render_evidence_chart(change, tmp_path / "change.png") is True
