"""Read-only Google Intelligence Connector Pack.

The pack deliberately has one narrow responsibility: retrieve data from the
five Google data products used by analytics teams and normalize each response
into the same tabular preview contract.  It never writes to a Google source,
never stores credentials, and never places query tokens in lineage metadata.

Authentication is supplied by process configuration. A refresh token and its
matching OAuth client credentials can renew short-lived access tokens in
memory. Tests can inject a transport function, so the contract remains useful
before OAuth/service-account setup is completed.
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from app.core.config import settings
from app.services.sql_sources import SqlSourceError, validate_read_only_query


ConnectorKind = str
SUPPORTED_CONNECTORS: tuple[ConnectorKind, ...] = (
    "google_drive",
    "google_sheets",
    "ga4",
    "search_console",
    "bigquery",
)

MAX_PREVIEW_ROWS = 100
MAX_SNAPSHOT_ROWS = 100_000


class ConnectorError(ValueError):
    """Safe, user-facing connector failure without provider response bodies."""


class ConnectorNotConfigured(ConnectorError):
    pass


class ConnectorRequestError(ConnectorError):
    pass


@dataclass(frozen=True)
class ConnectorResult:
    connector: ConnectorKind
    source_label: str
    source_uri: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    retrieved_at: str
    request_summary: Mapping[str, Any]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def preview(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(row) for row in self.rows[: max(1, min(limit, MAX_PREVIEW_ROWS))]]


Transport = Callable[[str, str, Mapping[str, Any] | None, Mapping[str, str] | None], Any]


class GoogleRestClient:
    """Minimal JSON/bytes client with injectable transport for deterministic tests."""

    def __init__(
        self,
        token: str | None = None,
        transport: Transport | None = None,
        timeout: float | None = None,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.token = (token if token is not None else settings.GOOGLE_ACCESS_TOKEN).strip()
        self.refresh_token = (refresh_token if refresh_token is not None else settings.GOOGLE_REFRESH_TOKEN).strip()
        self.client_id = (client_id if client_id is not None else settings.GOOGLE_OAUTH_CLIENT_ID).strip()
        self.client_secret = (client_secret if client_secret is not None else settings.GOOGLE_OAUTH_CLIENT_SECRET).strip()
        self._transport = transport
        self.timeout = timeout or settings.GOOGLE_CONNECTOR_TIMEOUT_SECONDS
        self._token_expires_at = 0.0
        self._refresh_lock = threading.Lock()

    @property
    def can_refresh(self) -> bool:
        return bool(self.refresh_token and self.client_id and self.client_secret)

    @property
    def configured(self) -> bool:
        return bool(self.token) or self.can_refresh or self._transport is not None

    def _require_auth(self) -> None:
        if not self.configured:
            raise ConnectorNotConfigured(
                "Google connectors are not configured. Set GOOGLE_ACCESS_TOKEN (read-only OAuth token) "
                "or configure GOOGLE_REFRESH_TOKEN with its OAuth client credentials."
            )

    def _refresh_access_token(self) -> None:
        if not self.can_refresh:
            raise ConnectorError("Google authorization expired. Reconnect the read-only Google account.")
        with self._refresh_lock:
            payload = urllib.parse.urlencode(
                {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                access_token = str(body.get("access_token") or "").strip()
                if not access_token:
                    raise ValueError("missing access token")
                self.token = access_token
                self._token_expires_at = time.monotonic() + max(60, int(body.get("expires_in") or 3600)) - 30
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                raise ConnectorError("Google authorization could not be renewed. Reconnect the read-only Google account.") from exc

    def _ensure_access_token(self) -> None:
        if not self.token:
            self._refresh_access_token()
        elif self.can_refresh and self._token_expires_at and time.monotonic() >= self._token_expires_at:
            self._refresh_access_token()

    def json(self, method: str, url: str, payload: Mapping[str, Any] | None = None, params: Mapping[str, str] | None = None) -> Any:
        self._require_auth()
        if self._transport is not None:
            try:
                return self._transport(method, url, payload, params)
            except ConnectorError:
                raise
            except Exception as exc:
                raise ConnectorError("The Google source could not be read. Check access and try again.") from exc

        self._ensure_access_token()
        return self._json_http(method, url, payload, params, allow_refresh=True)

    def _json_http(self, method: str, url: str, payload: Mapping[str, Any] | None, params: Mapping[str, str] | None, *, allow_refresh: bool) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url + query, data=body, method=method.upper())
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Do not expose Google response bodies: they may contain resource
            # names, query text, or account-specific details.
            if exc.code == 401 and allow_refresh and self.can_refresh:
                self._refresh_access_token()
                return self._json_http(method, url, payload, params, allow_refresh=False)
            if exc.code in {401, 403}:
                raise ConnectorError("Google denied read access. Reconnect with the required read-only scope.") from exc
            if exc.code == 404:
                raise ConnectorRequestError("The requested Google resource was not found.") from exc
            raise ConnectorError("Google could not complete the read request. Try again later.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ConnectorError("The Google source could not be reached. Check the connection and try again.") from exc

    def bytes(self, method: str, url: str, params: Mapping[str, str] | None = None) -> bytes:
        self._require_auth()
        if self._transport is not None:
            value = self._transport(method, url, None, params)
            if isinstance(value, bytes):
                return value
            raise ConnectorError("The connector transport did not return file bytes.")
        self._ensure_access_token()
        return self._bytes_http(method, url, params, allow_refresh=True)

    def _bytes_http(self, method: str, url: str, params: Mapping[str, str] | None, *, allow_refresh: bool) -> bytes:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        request = urllib.request.Request(url + query, method=method.upper())
        request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and allow_refresh and self.can_refresh:
                self._refresh_access_token()
                return self._bytes_http(method, url, params, allow_refresh=False)
            raise ConnectorError("Google could not download the requested file.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ConnectorError("Google could not download the requested file.") from exc


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip()).strip("_")
    return cleaned[:120] or "column"


def _matrix_rows(values: Sequence[Sequence[Any]]) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    if not values:
        raise ConnectorRequestError("The source returned no rows.")
    raw_headers = [str(v).strip() or f"column_{i + 1}" for i, v in enumerate(values[0])]
    headers: list[str] = []
    for header in raw_headers:
        candidate = _safe_name(header)
        base, suffix = candidate, 1
        while candidate in headers:
            suffix += 1
            candidate = f"{base}_{suffix}"
        headers.append(candidate)
    rows = []
    for raw in values[1:]:
        cells = list(raw)
        rows.append({headers[i]: (cells[i] if i < len(cells) else None) for i in range(len(headers))})
    if not rows:
        raise ConnectorRequestError("The source returned headers but no data rows.")
    return tuple(headers), tuple(rows)


def _result(kind: str, label: str, uri: str, columns: Sequence[str], rows: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> ConnectorResult:
    normalized = tuple({str(key): value for key, value in row.items()} for row in rows)
    if not normalized:
        raise ConnectorRequestError("The source returned no data rows.")
    return ConnectorResult(
        connector=kind,
        source_label=label,
        source_uri=uri,
        columns=tuple(str(column) for column in columns),
        rows=normalized,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        request_summary=dict(summary),
    )


class GoogleDriveConnector:
    kind = "google_drive"

    def __init__(self, client: GoogleRestClient):
        self.client = client

    def read(self, request: Mapping[str, Any]) -> ConnectorResult:
        file_id = str(request.get("file_id") or "").strip()
        if file_id:
            metadata = self.client.json(
                "GET",
                f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id, safe='')}",
                params={"fields": "id,name,mimeType,size,modifiedTime,webViewLink"},
            )
            if str(metadata.get("mimeType") or "") == "text/csv":
                raw = self.client.bytes(
                    "GET",
                    f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id, safe='')}",
                    params={"alt": "media"},
                )
                reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
                rows = [dict(row) for row in reader][: min(int(request.get("limit", 10_000)), MAX_SNAPSHOT_ROWS)]
                if rows:
                    return _result(self.kind, str(metadata.get("name") or "Drive CSV"), f"drive://{file_id}", rows[0].keys(), rows, {"file_id": file_id, "mode": "csv"})
            row = {key: metadata.get(key) for key in ("id", "name", "mimeType", "size", "modifiedTime", "webViewLink")}
            return _result(self.kind, str(metadata.get("name") or "Drive file"), f"drive://{file_id}", row.keys(), [row], {"file_id": file_id, "mode": "metadata"})
        response = self.client.json(
            "GET",
            "https://www.googleapis.com/drive/v3/files",
            params={"pageSize": str(min(int(request.get("limit", 50)), MAX_PREVIEW_ROWS)), "q": "trashed = false", "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink)"},
        )
        files = response.get("files") or []
        rows = [{key: item.get(key) for key in ("id", "name", "mimeType", "size", "modifiedTime", "webViewLink")} for item in files]
        return _result(self.kind, "Google Drive files", "drive://files", ("id", "name", "mimeType", "size", "modifiedTime", "webViewLink"), rows, {"mode": "catalog"})


class GoogleSheetsConnector:
    kind = "google_sheets"

    def __init__(self, client: GoogleRestClient):
        self.client = client

    def read(self, request: Mapping[str, Any]) -> ConnectorResult:
        spreadsheet_id = str(request.get("spreadsheet_id") or "").strip()
        cell_range = str(request.get("range") or "Sheet1").strip()
        if not spreadsheet_id:
            raise ConnectorRequestError("spreadsheet_id is required for Google Sheets.")
        encoded_range = urllib.parse.quote(cell_range, safe="")
        response = self.client.json("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{encoded_range}")
        columns, rows = _matrix_rows(response.get("values") or [])
        return _result(self.kind, f"Google Sheet · {cell_range}", f"sheets://{spreadsheet_id}/{cell_range}", columns, rows[:MAX_SNAPSHOT_ROWS], {"spreadsheet_id": spreadsheet_id, "range": cell_range})


class GA4Connector:
    kind = "ga4"

    def __init__(self, client: GoogleRestClient):
        self.client = client

    def read(self, request: Mapping[str, Any]) -> ConnectorResult:
        property_id = str(request.get("property_id") or "").strip().removeprefix("properties/")
        if not property_id.isdigit():
            raise ConnectorRequestError("property_id must be a numeric GA4 property id.")
        start = str(request.get("start_date") or "28daysAgo")
        end = str(request.get("end_date") or "yesterday")
        dimensions = [str(v) for v in (request.get("dimensions") or ["date"])][:9]
        metrics = [str(v) for v in (request.get("metrics") or ["activeUsers", "sessions"])][:10]
        if not dimensions or not metrics:
            raise ConnectorRequestError("GA4 requires at least one dimension and one metric.")
        payload = {"dateRanges": [{"startDate": start, "endDate": end}], "dimensions": [{"name": v} for v in dimensions], "metrics": [{"name": v} for v in metrics], "limit": min(int(request.get("limit", 10_000)), MAX_SNAPSHOT_ROWS), "keepEmptyRows": False}
        response = self.client.json("POST", f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport", payload)
        headers = [v.get("name") for v in response.get("dimensionHeaders", [])] + [v.get("name") for v in response.get("metricHeaders", [])]
        rows = []
        for item in response.get("rows") or []:
            values = [v.get("value") for v in item.get("dimensionValues", [])] + [v.get("value") for v in item.get("metricValues", [])]
            rows.append({headers[i]: values[i] if i < len(values) else None for i in range(len(headers))})
        return _result(self.kind, f"GA4 property {property_id}", f"ga4://properties/{property_id}", headers, rows, {"property_id": property_id, "start_date": start, "end_date": end, "dimensions": dimensions, "metrics": metrics})


class SearchConsoleConnector:
    kind = "search_console"

    def __init__(self, client: GoogleRestClient):
        self.client = client

    def read(self, request: Mapping[str, Any]) -> ConnectorResult:
        site_url = str(request.get("site_url") or "").strip()
        start = str(request.get("start_date") or "28daysAgo")
        end = str(request.get("end_date") or "yesterday")
        if not site_url or not (site_url.startswith("http://") or site_url.startswith("https://")):
            raise ConnectorRequestError("site_url must be a verified Search Console URL.")
        dimensions = [str(v) for v in (request.get("dimensions") or ["date"])][:5]
        payload = {"startDate": start, "endDate": end, "dimensions": dimensions, "rowLimit": min(int(request.get("limit", 10_000)), MAX_SNAPSHOT_ROWS), "dataState": "final"}
        encoded_site = urllib.parse.quote(site_url, safe="")
        response = self.client.json("POST", f"https://searchconsole.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query", payload)
        metric_names = ("clicks", "impressions", "ctr", "position")
        rows = []
        for item in response.get("rows") or []:
            keys = list(item.get("keys") or [])
            row = {dimensions[i]: keys[i] if i < len(keys) else None for i in range(len(dimensions))}
            row.update({name: item.get(name) for name in metric_names})
            rows.append(row)
        return _result(self.kind, f"Search Console · {site_url}", f"search-console://{site_url}", [*dimensions, *metric_names], rows, {"site_url": site_url, "start_date": start, "end_date": end, "dimensions": dimensions})


class BigQueryConnector:
    kind = "bigquery"

    def __init__(self, client: GoogleRestClient):
        self.client = client

    def read(self, request: Mapping[str, Any]) -> ConnectorResult:
        project_id = str(request.get("project_id") or "").strip()
        query = str(request.get("query") or "")
        if not project_id:
            raise ConnectorRequestError("project_id is required for BigQuery.")
        try:
            safe_query = validate_read_only_query(query)
        except SqlSourceError as exc:
            raise ConnectorRequestError(str(exc)) from exc
        limit = min(int(request.get("limit", 10_000)), MAX_SNAPSHOT_ROWS)
        wrapped_query = f"SELECT * FROM ({safe_query}) AS analytics_source LIMIT {limit}"
        payload = {"query": wrapped_query, "useLegacySql": False, "timeoutMs": 10_000, "maxResults": limit, "dryRun": False}
        response = self.client.json("POST", f"https://bigquery.googleapis.com/bigquery/v2/projects/{urllib.parse.quote(project_id, safe='')}/queries", payload)
        if response.get("jobComplete") is False:
            raise ConnectorError("BigQuery is still processing this request. Narrow the query and try again.")
        schema_fields = [field.get("name") for field in (response.get("schema") or {}).get("fields", [])]
        rows = []
        for row in response.get("rows") or []:
            values = [cell.get("v") for cell in row.get("f", [])]
            rows.append({schema_fields[i]: values[i] if i < len(values) else None for i in range(len(schema_fields))})
        return _result(self.kind, f"BigQuery · {project_id}", f"bigquery://{project_id}", schema_fields, rows, {"project_id": project_id, "query_fingerprint": __import__("hashlib").sha256(safe_query.encode()).hexdigest()})


class ConnectorRegistry:
    """Data-manager registry: each adapter is read-only and independently testable."""

    def __init__(self, client: GoogleRestClient | None = None):
        client = client or GoogleRestClient()
        self._connectors = {
            "google_drive": GoogleDriveConnector(client),
            "google_sheets": GoogleSheetsConnector(client),
            "ga4": GA4Connector(client),
            "search_console": SearchConsoleConnector(client),
            "bigquery": BigQueryConnector(client),
        }

    def catalog(self) -> list[dict[str, Any]]:
        configured = any(getattr(item, "client", None) and item.client.configured for item in self._connectors.values())
        return [
            {
                "id": kind,
                "name": {"google_drive": "Google Drive", "google_sheets": "Google Sheets", "ga4": "Google Analytics 4", "search_console": "Google Search Console", "bigquery": "BigQuery"}[kind],
                "read_only": True,
                "configured": configured,
                "capabilities": {"google_drive": ["list files", "inspect file metadata"], "google_sheets": ["read ranges"], "ga4": ["run reports"], "search_console": ["query search performance"], "bigquery": ["run SELECT/WITH queries"]}[kind],
                "credential_note": "Read-only Google authorization is required; credentials are never stored by the app.",
            }
            for kind in SUPPORTED_CONNECTORS
        ]

    def read(self, kind: str, request: Mapping[str, Any]) -> ConnectorResult:
        connector = self._connectors.get(kind)
        if connector is None:
            raise ConnectorRequestError(f"Unsupported connector. Choose one of: {', '.join(SUPPORTED_CONNECTORS)}.")
        return connector.read(request)  # type: ignore[attr-defined]


def default_registry() -> ConnectorRegistry:
    return ConnectorRegistry()
