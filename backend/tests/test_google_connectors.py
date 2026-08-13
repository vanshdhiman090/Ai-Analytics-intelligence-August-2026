from __future__ import annotations

import io
import json
import urllib.error

import pytest

from app.services.google_connectors import ConnectorRegistry, GoogleRestClient, ConnectorRequestError


def fake_transport(method, url, payload, params):
    if "sheets.googleapis.com" in url:
        return {"values": [["Date", "Sessions"], ["2026-08-01", 12], ["2026-08-02", 18]]}
    if "analyticsdata.googleapis.com" in url:
        return {
            "dimensionHeaders": [{"name": "date"}],
            "metricHeaders": [{"name": "sessions"}],
            "rows": [{"dimensionValues": [{"value": "20260801"}], "metricValues": [{"value": "12"}]}],
        }
    if "searchconsole.googleapis.com" in url:
        return {"rows": [{"keys": ["2026-08-01"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 3.2}]}
    if "bigquery.googleapis.com" in url:
        return {"jobComplete": True, "schema": {"fields": [{"name": "channel"}, {"name": "orders"}]}, "rows": [{"f": [{"v": "organic"}, {"v": "9"}]}]}
    if "drive.googleapis.com" in url or "www.googleapis.com/drive" in url:
        return {"files": [{"id": "f1", "name": "sales.csv", "mimeType": "text/csv", "size": "12"}]}
    raise AssertionError(url)


@pytest.fixture()
def registry():
    return ConnectorRegistry(GoogleRestClient(transport=fake_transport))


def test_catalog_is_data_only_and_read_only(registry):
    catalog = registry.catalog()
    assert {item["id"] for item in catalog} == {"google_drive", "google_sheets", "ga4", "search_console", "bigquery"}
    assert all(item["read_only"] for item in catalog)
    assert all(item["configured"] for item in catalog)


def test_sheets_normalizes_matrix_to_named_rows(registry):
    result = registry.read("google_sheets", {"spreadsheet_id": "sheet-1", "range": "Data!A1:B3"})
    assert result.columns == ("Date", "Sessions")
    assert result.rows[1]["Sessions"] == 18
    assert result.source_uri == "sheets://sheet-1/Data!A1:B3"


def test_ga4_normalizes_dimension_and_metric_headers(registry):
    result = registry.read("ga4", {"property_id": "12345"})
    assert result.columns == ("date", "sessions")
    assert result.rows == ({"date": "20260801", "sessions": "12"},)


def test_search_console_preserves_metrics_and_lineage(registry):
    result = registry.read("search_console", {"site_url": "https://example.com", "start_date": "2026-08-01", "end_date": "2026-08-07"})
    assert result.rows[0]["clicks"] == 10
    assert result.request_summary["site_url"] == "https://example.com"


def test_bigquery_rejects_write_queries_before_network(registry):
    with pytest.raises(ConnectorRequestError, match="read-only"):
        registry.read("bigquery", {"project_id": "demo", "query": "DELETE FROM demo.table"})


def test_bigquery_returns_query_fingerprint_not_query_text(registry):
    result = registry.read("bigquery", {"project_id": "demo", "query": "SELECT channel, orders FROM demo.table"})
    assert result.rows[0]["channel"] == "organic"
    assert "query_fingerprint" in result.request_summary
    assert "SELECT" not in str(result.request_summary)


def test_drive_csv_file_is_normalized_as_rows():
    def transport(method, url, payload, params):
        if params and params.get("alt") == "media":
            return b"date,sessions\n2026-08-01,12\n"
        return {"id": "f1", "name": "sales.csv", "mimeType": "text/csv", "size": "20"}

    result = ConnectorRegistry(GoogleRestClient(transport=transport)).read("google_drive", {"file_id": "f1"})
    assert result.columns == ("date", "sessions")
    assert result.rows[0]["sessions"] == "12"


class _HttpResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def test_expired_access_token_is_refreshed_and_request_is_retried(monkeypatch):
    calls = {"api": 0, "token": 0}

    def fake_urlopen(request, timeout):
        assert timeout > 0
        if request.full_url == "https://oauth2.googleapis.com/token":
            calls["token"] += 1
            assert b"refresh_token=refresh-value" in request.data
            return _HttpResponse({"access_token": "fresh-token", "expires_in": 3600})
        calls["api"] += 1
        if calls["api"] == 1:
            raise urllib.error.HTTPError(request.full_url, 401, "expired", {}, io.BytesIO())
        assert request.get_header("Authorization") == "Bearer fresh-token"
        return _HttpResponse({"files": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = GoogleRestClient(
        token="expired-token",
        refresh_token="refresh-value",
        client_id="client-id",
        client_secret="client-secret",
    )

    assert client.json("GET", "https://www.googleapis.com/drive/v3/files") == {"files": []}
    assert calls == {"api": 2, "token": 1}
    assert client.token == "fresh-token"


def test_refresh_credentials_configure_client_without_access_token(monkeypatch):
    def fake_urlopen(request, timeout):
        if request.full_url == "https://oauth2.googleapis.com/token":
            return _HttpResponse({"access_token": "fresh-token", "expires_in": 3600})
        assert request.get_header("Authorization") == "Bearer fresh-token"
        return _HttpResponse({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = GoogleRestClient(
        token="",
        refresh_token="refresh-value",
        client_id="client-id",
        client_secret="client-secret",
    )

    assert client.configured is True
    assert client.json("GET", "https://example.test") == {"ok": True}
