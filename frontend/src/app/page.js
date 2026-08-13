"use client";

import { useEffect, useState } from "react";
import PipelineTracker from "@/components/PipelineTracker";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";
const ACTIVE_STATUSES = new Set(["queued", "running", "active"]);

// Attach the API key header to every request when configured.
function apiHeaders(extra = {}) {
  return API_KEY ? { ...extra, "X-API-Key": API_KEY } : extra;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: apiHeaders(options.headers),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function formatDate(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export default function Home() {
  const [step, setStep] = useState("upload");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploadedDataset, setUploadedDataset] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [roughPrompt, setRoughPrompt] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [checkpoint, setCheckpoint] = useState(null);
  const [answer, setAnswer] = useState("");
  const [sessionData, setSessionData] = useState(null);
  const [recentSessions, setRecentSessions] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const [evaluationRunning, setEvaluationRunning] = useState(false);
  const [analysisObjectives, setAnalysisObjectives] = useState(["drivers", "trends", "segments"]);
  const [workflowMode, setWorkflowMode] = useState("fast");
  const [revenueReportingCurrency, setRevenueReportingCurrency] = useState("");
  const [revenueTimezone, setRevenueTimezone] = useState("");
  const [requestedOutputs, setRequestedOutputs] = useState([]);
  const [sourceKind, setSourceKind] = useState("file");
  const [sqlConnection, setSqlConnection] = useState("");
  const [sqlQuery, setSqlQuery] = useState("SELECT * FROM your_table");
  const [googleConnector, setGoogleConnector] = useState("google_sheets");
  const [googleSpreadsheetId, setGoogleSpreadsheetId] = useState("");
  const [googleRange, setGoogleRange] = useState("Sheet1");
  const [ga4PropertyId, setGa4PropertyId] = useState("");
  const [searchSiteUrl, setSearchSiteUrl] = useState("");
  const [connectorProjectId, setConnectorProjectId] = useState("");
  const [connectorQuery, setConnectorQuery] = useState("SELECT * FROM `project.dataset.table`");
  const [connectorStartDate, setConnectorStartDate] = useState("28daysAgo");
  const [connectorEndDate, setConnectorEndDate] = useState("yesterday");
  const [projectSearch, setProjectSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("all");
  const [draftSaved, setDraftSaved] = useState(false);
  // Live progress message from the SSE stream
  const [progressMsg, setProgressMsg] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function restoreWorkspace() {
      try {
        const [history, quality] = await Promise.all([
          requestJson(`${API_BASE}/sessions?limit=8`),
          requestJson(`${API_BASE}/evaluations/latest`).catch(() => null),
        ]);
        if (!cancelled) setRecentSessions(history.sessions || []);
        if (!cancelled && quality) setEvaluation(quality);
      } catch {
        // The start screen remains usable and displays connection errors on action.
      }
    }
    restoreWorkspace();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!wizardOpen || !roughPrompt.trim()) return undefined;
    const timer = window.setTimeout(() => {
      window.localStorage.setItem("analytics:draft", JSON.stringify({ roughPrompt, analysisObjectives, savedAt: new Date().toISOString() }));
      setDraftSaved(true);
    }, 500);
    setDraftSaved(false);
    return () => window.clearTimeout(timer);
  }, [roughPrompt, analysisObjectives, wizardOpen]);

  // ── SSE live progress + polling fallback ───────────────────────────────
  useEffect(() => {
    if (!sessionId || step !== "running") return undefined;
    let es = null;
    let pollTimer = null;
    let closed = false;

    function cleanup() {
      closed = true;
      if (es) { es.close(); es = null; }
      if (pollTimer) { window.clearTimeout(pollTimer); pollTimer = null; }
    }

    // SSE: subscribe to live progress events from the backend
    function openSSE() {
      es = new EventSource(`${API_BASE}/sessions/${sessionId}/events`);
      es.onmessage = (evt) => {
        try {
          const event = JSON.parse(evt.data);
          if (event.message) setProgressMsg(event.message);
          // On 'done', fetch final session state once
          if (event.stage === "done") {
            es.close();
            fetchSession();
          }
        } catch { /* ignore parse errors */ }
      };
      es.onerror = () => {
        // SSE failed (e.g. proxy, older browser) — fall back to polling
        if (es) { es.close(); es = null; }
        if (!closed) schedulePoll(2000);
      };
    }

    // Polling fallback: used after SSE error, or for paused sessions
    async function fetchSession() {
      try {
        const data = await requestJson(`${API_BASE}/sessions/${sessionId}`);
        if (!closed) applySession(data);
      } catch (err) {
        if (!closed) {
          setError(`${err.message}. The run is saved — reconnect and open it from Recent analyses.`);
          schedulePoll(5000);
        }
      }
    }

    function schedulePoll(ms) {
      if (!closed) pollTimer = window.setTimeout(fetchSession, ms);
    }

    openSSE();
    // Also do an immediate HTTP fetch so the UI state is correct right away
    fetchSession();

    return cleanup;
  }, [sessionId, step]);

  function applySession(data) {
    setSessionData(data);
    setError(null);
    if (data.status === "paused_for_input") {
      setCheckpoint(data.checkpoint);
      setStep("checkpoint");
    } else if (data.status === "complete") {
      setStep("report");
      refreshHistory();
    } else if (data.status === "error") {
      setStep("error");
      setError(data.error || "The analysis stopped and can be retried from its last saved checkpoint.");
      refreshHistory();
    } else {
      setStep("running");
    }
  }

  async function refreshHistory() {
    try {
      const history = await requestJson(`${API_BASE}/sessions?limit=8`);
      setRecentSessions(history.sessions || []);
    } catch {
      // History is secondary to the active run.
    }
  }

  async function openSession(id, showErrors = true) {
    try {
      const data = await requestJson(`${API_BASE}/sessions/${id}`);
      setWizardOpen(false);
      setSessionId(id);
      window.localStorage.setItem("analytics:last-session", id);
      applySession(data);
    } catch (openError) {
      if (showErrors) setError(openError.message);
    }
  }

  async function inspectDataset() {
    setLoading(true);
    setError(null);
    try {
      const uploads = await Promise.all(selectedFiles.map(async (file) => {
        const formData = new FormData();
        formData.append("file", file);
        return requestJson(`${API_BASE}/datasets`, { method: "POST", body: formData });
      }));
      const model = await requestJson(`${API_BASE}/data-model/inspect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset_ids: uploads.map((item) => item.dataset_id) }),
      });
      setUploadedDataset(model);
      setWizardStep(3);
    } catch (startError) {
      setError(startError.message || "The dataset could not be inspected.");
    } finally {
      setLoading(false);
    }
  }

  async function inspectSqlDataset() {
    setLoading(true); setError(null);
    try {
      const upload = await requestJson(`${API_BASE}/datasets/sql`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ connection_url: sqlConnection, query: sqlQuery, label: "SQL analysis snapshot" }) });
      const model = await requestJson(`${API_BASE}/data-model/inspect`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset_ids: [upload.dataset_id] }) });
      setUploadedDataset(model); setWizardStep(3);
    } catch (startError) { setError(startError.message || "The SQL data could not be inspected."); } finally { setLoading(false); }
  }

  async function inspectConnectorDataset() {
    setLoading(true); setError(null);
    const request = { connector: googleConnector, limit: 10000 };
    if (googleConnector === "google_sheets") Object.assign(request, { spreadsheet_id: googleSpreadsheetId, range: googleRange });
    if (googleConnector === "ga4") Object.assign(request, { property_id: ga4PropertyId, start_date: connectorStartDate, end_date: connectorEndDate });
    if (googleConnector === "search_console") Object.assign(request, { site_url: searchSiteUrl, start_date: connectorStartDate, end_date: connectorEndDate });
    if (googleConnector === "bigquery") Object.assign(request, { project_id: connectorProjectId, query: connectorQuery });
    try {
      const upload = await requestJson(`${API_BASE}/connectors/snapshot`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
      const model = await requestJson(`${API_BASE}/data-model/inspect`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset_ids: [upload.dataset_id] }) });
      setUploadedDataset(model); setWizardStep(3);
    } catch (connectorError) { setError(connectorError.message || "The Google source could not be read."); } finally { setLoading(false); }
  }

  function selectFiles(fileList) {
    const received = Array.from(fileList || []);
    const supported = received.filter((file) => /\.(csv|xlsx)$/i.test(file.name));
    setIsDragging(false);
    if (!received.length) {
      setSelectedFiles([]);
      setError("No file was received. Click Choose files and select a CSV or Excel file.");
      return;
    }
    if (!supported.length) {
      setSelectedFiles([]);
      setError("Only CSV and Excel (.xlsx) files are supported.");
      return;
    }
    setSelectedFiles(supported.slice(0, 10));
    setError(received.length > 10 ? "The first 10 supported files were added." : supported.length < received.length ? "Unsupported files were skipped; CSV and Excel files were added." : null);
  }

  async function startPipeline() {
    setLoading(true);
    setError(null);
    try {
      const data = await requestJson(`${API_BASE}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset_ids: uploadedDataset.datasets.map((item) => item.dataset_id),
          joins: uploadedDataset.proposed_joins.map((item) => ({ relationship_id: item.relationship_id })),
          rough_prompt: roughPrompt,
          business_question: roughPrompt,
          analysis_objectives: analysisObjectives,
          workflow_mode: workflowMode,
          ...(analysisObjectives.includes("root_cause") && revenueReportingCurrency.trim() ? { revenue_reporting_currency: revenueReportingCurrency.trim().toUpperCase() } : {}),
          ...(analysisObjectives.includes("root_cause") && revenueTimezone.trim() ? { revenue_timezone: revenueTimezone.trim() } : {}),
        }),
      });
      setSessionId(data.session_id);
      setSessionData({ ...data, current_stage: "ask" });
      window.localStorage.setItem("analytics:last-session", data.session_id);
      window.localStorage.removeItem("analytics:draft");
      setWizardOpen(false);
      setStep("running");
      refreshHistory();
    } catch (startError) {
      setError(startError.message || "The analysis could not be started.");
    } finally {
      setLoading(false);
    }
  }

  async function submitAnswer(answerOverride = answer) {
    setLoading(true);
    setError(null);
    try {
      await requestJson(`${API_BASE}/sessions/${sessionId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: answerOverride }),
      });
      setAnswer("");
      setCheckpoint(null);
      setStep("running");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setLoading(false);
    }
  }

  async function retryAnalysis() {
    setLoading(true);
    setError(null);
    try {
      // The server may have recovered or advanced while this browser still
      // shows an older error screen. Reconcile first so we never retry a run
      // that is already waiting for the user's checkpoint answer.
      const current = await requestJson(`${API_BASE}/sessions/${sessionId}`);
      if (current.status !== "error") {
        applySession(current);
        return;
      }
      await requestJson(`${API_BASE}/sessions/${sessionId}/retry`, { method: "POST" });
      setStep("running");
    } catch (retryError) {
      setError(retryError.message);
    } finally {
      setLoading(false);
    }
  }

  function newAnalysis() {
    setStep("upload");
    setWizardOpen(true);
    setWizardStep(1);
    setSelectedFiles([]);
    setSourceKind("file"); setSqlConnection(""); setSqlQuery("SELECT * FROM your_table");
    setUploadedDataset(null);
    const draft = JSON.parse(window.localStorage.getItem("analytics:draft") || "null");
    setRoughPrompt(draft?.roughPrompt || "");
    setAnalysisObjectives(draft?.analysisObjectives || ["drivers", "trends", "segments"]);
    setWorkflowMode("fast");
    setRequestedOutputs([]);
    setSessionId(null);
    setSessionData(null);
    setCheckpoint(null);
    setAnswer("");
    setError(null);
    window.localStorage.removeItem("analytics:last-session");
    refreshHistory();
  }

  function returnDashboard() {
    setStep("upload");
    setWizardOpen(false);
    setWizardStep(1);
    setError(null);
    refreshHistory();
  }

  function toggleObjective(objective) {
    setAnalysisObjectives((current) => current.includes(objective) ? current.filter((item) => item !== objective) : [...current, objective]);
  }

  async function runAccuracyEvaluation() {
    setEvaluationRunning(true);
    try {
      const quality = await requestJson(`${API_BASE}/evaluations/run`, { method: "POST" });
      setEvaluation(quality);
    } catch (evaluationError) {
      setError(`Accuracy evaluation could not complete: ${evaluationError.message}`);
    } finally {
      setEvaluationRunning(false);
    }
  }

  const stage = checkpoint?.stage || sessionData?.current_stage || "ask";
  const trackerStatus = step === "report" ? "complete" : step === "checkpoint" ? "paused_for_input" : sessionData?.status || "running";
  const filteredSessions = recentSessions.filter((session) => {
    const matchesText = (session.business_task || session.session_id).toLowerCase().includes(projectSearch.toLowerCase());
    return matchesText && (projectFilter === "all" || session.status === projectFilter);
  });

  return (
    <main style={{ maxWidth: 1120, margin: "0 auto", padding: "34px 24px 70px" }}>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 20, alignItems: "flex-start", marginBottom: 36 }}>
        <div>
          <div className="mono" style={{ color: "var(--teal)", fontSize: 11, letterSpacing: "0.09em", textTransform: "uppercase" }}>Decision intelligence</div>
          <h1 style={{ fontSize: 30, marginTop: 6 }}>AI Analytics Workspace</h1>
          <p style={{ color: "var(--muted)", marginTop: 6 }}>From raw data to an evidence-linked decision package.</p>
        </div>
        <div style={{ display: "flex", gap: 9, alignItems: "center" }}>
          <EvaluationBadge evaluation={evaluation} />
          {(wizardOpen || step !== "upload") && <button onClick={returnDashboard} style={secondaryButton}>Project dashboard</button>}
          {!wizardOpen && step === "upload" && <button onClick={newAnalysis} style={primaryButton}>New analysis</button>}
        </div>
      </header>

      {step !== "upload" && <PipelineTracker currentStage={stage} status={trackerStatus} />}

      {error && (
        <div role="alert" style={{ background: "rgba(232,102,61,0.1)", border: "1px solid var(--danger)", borderRadius: 9, padding: 14, marginBottom: 20, color: "var(--danger)", fontSize: 14 }}>
          {error}
        </div>
      )}

      {step === "upload" && !wizardOpen && <ProjectDashboard sessions={filteredSessions} allSessions={recentSessions} evaluation={evaluation} search={projectSearch} onSearch={setProjectSearch} filter={projectFilter} onFilter={setProjectFilter} onNew={newAnalysis} onOpen={openSession} onRunEvaluation={runAccuracyEvaluation} evaluationRunning={evaluationRunning} />}

      {step === "upload" && wizardOpen && <WizardProgress current={wizardStep} />}

      {step === "upload" && wizardOpen && wizardStep === 1 && (
        <div style={panelStyle}>
          <span className="mono wizard-kicker">Step 1 · Define the decision</span>
          <h2 className="wizard-title">What should this project help decide?</h2>
          <p className="wizard-copy">Start with the business decision, not a chart request. The agent will translate it into a defensible analytical scope.</p>
          <label style={labelStyle}>Analysis pace</label>
          <div className="objective-grid"><button type="button" onClick={() => setWorkflowMode("fast")} className={workflowMode === "fast" ? "selected" : ""}><span>{workflowMode === "fast" ? "✓" : "+"}</span>Fast Analysis</button><button type="button" onClick={() => setWorkflowMode("professional")} className={workflowMode === "professional" ? "selected" : ""}><span>{workflowMode === "professional" ? "✓" : "+"}</span>Full Professional Workflow</button></div>
          <p className="wizard-copy" style={{ fontSize: 13 }}>{workflowMode === "fast" ? "Fast: validated analysis with a final choice of deliverable." : "Professional: you approve Ask, Prepare, Process, and Analyze before the next phase."}</p>
          <label style={labelStyle}>Business question or decision</label>
          <textarea value={roughPrompt} onChange={(event) => setRoughPrompt(event.target.value)} placeholder="e.g. Which customer segments and products drive profitable growth, and where should leadership act next?" rows={5} style={textareaStyle} />
          <label style={labelStyle}>Analytical objectives</label>
          <div className="objective-grid">{[["drivers","Explain drivers"],["trends","Measure trends"],["segments","Compare segments"],["quality","Audit data quality"],["root_cause","Root cause analysis"]].map(([id,label]) => <button type="button" key={id} onClick={() => toggleObjective(id)} className={analysisObjectives.includes(id) ? "selected" : ""}><span>{analysisObjectives.includes(id) ? "✓" : "+"}</span>{label}</button>)}</div>
          {analysisObjectives.includes("root_cause") && <div className="preflight-notice"><strong>Revenue metric governance (only when the KPI is net_revenue)</strong><p>The agent will never guess monetary policy. Enter the reporting currency and IANA timezone if this investigation uses the canonical Revenue metric; otherwise leave these blank.</p><div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 10 }}><div><label style={labelStyle}>Currency</label><input value={revenueReportingCurrency} onChange={(event) => setRevenueReportingCurrency(event.target.value)} placeholder="EUR" maxLength={3} style={{ ...textareaStyle, minHeight: 42 }} /></div><div><label style={labelStyle}>Timezone</label><input value={revenueTimezone} onChange={(event) => setRevenueTimezone(event.target.value)} placeholder="Europe/Berlin" style={{ ...textareaStyle, minHeight: 42 }} /></div></div></div>}
          <div className="wizard-actions"><span className="draft-status">{draftSaved ? "Draft saved locally" : roughPrompt ? "Saving draft…" : "Draft starts when you type"}</span><button onClick={() => setWizardStep(2)} disabled={roughPrompt.trim().length < 3 || !analysisObjectives.length} style={{ ...primaryButton, opacity: roughPrompt.trim().length < 3 || !analysisObjectives.length ? .45 : 1 }}>Continue to data</button></div>
        </div>
      )}

      {step === "upload" && wizardOpen && wizardStep === 2 && (
        <>
          <div style={panelStyle}>
            <span className="mono wizard-kicker">Step 2 · Add data sources</span>
            <h2 className="wizard-title">Upload the evidence for this decision</h2>
            <p className="wizard-copy">Use one file for a simple analysis or multiple related files for a professional data model.</p>
            <div className="objective-grid" style={{ marginBottom: 18 }}><button type="button" onClick={() => setSourceKind("file")} className={sourceKind === "file" ? "selected" : ""}><span>{sourceKind === "file" ? "✓" : "+"}</span>CSV or Excel</button><button type="button" onClick={() => setSourceKind("sql")} className={sourceKind === "sql" ? "selected" : ""}><span>{sourceKind === "sql" ? "✓" : "+"}</span>SQL database</button><button type="button" onClick={() => setSourceKind("google")} className={sourceKind === "google" ? "selected" : ""}><span>{sourceKind === "google" ? "✓" : "+"}</span>Google data pack</button></div>
            {sourceKind === "sql" && <><label style={labelStyle}>Database connection URL</label><input value={sqlConnection} onChange={(event) => setSqlConnection(event.target.value)} placeholder="postgresql://user:password@host:5432/database" style={{ ...textareaStyle, minHeight: 42 }} /><p className="wizard-copy" style={{ fontSize: 12 }}>Used once to make a local analysis snapshot. It is never saved by this app.</p><label style={labelStyle}>Read-only SQL query</label><textarea value={sqlQuery} onChange={(event) => setSqlQuery(event.target.value)} rows={4} style={textareaStyle} /><div className="wizard-actions"><button onClick={() => setWizardStep(1)} style={secondaryButton}>Back</button><button onClick={inspectSqlDataset} disabled={loading || !sqlConnection.trim() || !sqlQuery.trim()} style={{ ...primaryButton, opacity: loading || !sqlConnection.trim() || !sqlQuery.trim() ? .5 : 1 }}>{loading ? "Reading database…" : "Review SQL snapshot"}</button></div></>}
            {sourceKind === "google" && <>
              <label style={labelStyle}>Google source</label>
              <select value={googleConnector} onChange={(event) => setGoogleConnector(event.target.value)} style={{ ...textareaStyle, minHeight: 42 }}><option value="google_drive">Google Drive (file catalogue)</option><option value="google_sheets">Google Sheets (range)</option><option value="ga4">GA4 (report)</option><option value="search_console">Search Console (performance)</option><option value="bigquery">BigQuery (read-only SQL)</option></select>
              <p className="wizard-copy" style={{ fontSize: 12 }}>Read-only only. The server must be configured with a Google read-only token; credentials are never saved by this app.</p>
              {googleConnector === "google_drive" && <p className="wizard-copy">This first release catalogs accessible Drive files. Use Google Sheets or BigQuery when you need table rows.</p>}
              {googleConnector === "google_sheets" && <><label style={labelStyle}>Spreadsheet ID</label><input value={googleSpreadsheetId} onChange={(event) => setGoogleSpreadsheetId(event.target.value)} placeholder="From the Google Sheets URL" style={{ ...textareaStyle, minHeight: 42 }} /><label style={labelStyle}>Range</label><input value={googleRange} onChange={(event) => setGoogleRange(event.target.value)} placeholder="Sheet1!A1:Z1000" style={{ ...textareaStyle, minHeight: 42 }} /></>}
              {googleConnector === "ga4" && <><label style={labelStyle}>GA4 property ID</label><input value={ga4PropertyId} onChange={(event) => setGa4PropertyId(event.target.value)} placeholder="123456789" style={{ ...textareaStyle, minHeight: 42 }} /><DateRangeFields start={connectorStartDate} end={connectorEndDate} setStart={setConnectorStartDate} setEnd={setConnectorEndDate} /></>}
              {googleConnector === "search_console" && <><label style={labelStyle}>Verified site URL</label><input value={searchSiteUrl} onChange={(event) => setSearchSiteUrl(event.target.value)} placeholder="https://example.com" style={{ ...textareaStyle, minHeight: 42 }} /><DateRangeFields start={connectorStartDate} end={connectorEndDate} setStart={setConnectorStartDate} setEnd={setConnectorEndDate} /></>}
              {googleConnector === "bigquery" && <><label style={labelStyle}>Google Cloud project ID</label><input value={connectorProjectId} onChange={(event) => setConnectorProjectId(event.target.value)} placeholder="analytics-project" style={{ ...textareaStyle, minHeight: 42 }} /><label style={labelStyle}>Read-only query</label><textarea value={connectorQuery} onChange={(event) => setConnectorQuery(event.target.value)} rows={4} style={textareaStyle} /></>}
              <div className="wizard-actions"><button onClick={() => setWizardStep(1)} style={secondaryButton}>Back</button><button onClick={inspectConnectorDataset} disabled={loading || (googleConnector === "google_sheets" && !googleSpreadsheetId.trim()) || (googleConnector === "ga4" && !ga4PropertyId.trim()) || (googleConnector === "search_console" && !searchSiteUrl.trim()) || (googleConnector === "bigquery" && (!connectorProjectId.trim() || !connectorQuery.trim()))} style={{ ...primaryButton, opacity: loading ? .5 : 1 }}>{loading ? "Reading Google source…" : "Review read-only snapshot"}</button></div>
            </>}
            {sourceKind === "file" && <>
            <label style={labelStyle}>Dataset</label>
            <label
              onDragEnter={(event) => { event.preventDefault(); event.stopPropagation(); setIsDragging(true); }}
              onDragOver={(event) => { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = "copy"; setIsDragging(true); }}
              onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setIsDragging(false); }}
              onDrop={(event) => { event.preventDefault(); event.stopPropagation(); selectFiles(event.dataTransfer.files); }}
              style={{ display: "block", padding: "28px 18px", marginBottom: 18, textAlign: "center", background: isDragging ? "rgba(61,220,151,0.08)" : "var(--panel-raised)", border: `1px dashed ${isDragging ? "var(--teal)" : "var(--border)"}`, borderRadius: 10, cursor: "pointer" }}
            >
              <input type="file" accept=".csv,.xlsx" multiple onChange={(event) => selectFiles(event.target.files)} style={{ display: "none" }} />
              <div style={{ fontSize: 14, color: selectedFiles.length ? "var(--text)" : "var(--muted)" }}>{selectedFiles.length ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} selected` : "Drop up to 10 CSV or Excel files here, or click to browse"}</div>
              {!selectedFiles.length && <div className="choose-files-hint">Choose files</div>}
              {selectedFiles.length > 0 && <div className="multi-file-list">{selectedFiles.map((file) => <span key={`${file.name}-${file.size}`}>{file.name}<small>{(file.size / 1024 / 1024).toFixed(2)} MB</small></span>)}</div>}
            </label>
            <div className="wizard-actions"><button onClick={() => setWizardStep(1)} style={secondaryButton}>Back</button><button onClick={inspectDataset} disabled={loading || !selectedFiles.length} style={{ ...primaryButton, opacity: loading || !selectedFiles.length ? 0.5 : 1 }}>{loading ? "Profiling files and relationships…" : selectedFiles.length > 1 ? "Build and review data model" : "Review dataset"}</button></div>
            </>}
          </div>
        </>
      )}

      {step === "upload" && wizardOpen && wizardStep === 3 && uploadedDataset && (
        <DatasetReview dataset={uploadedDataset} onBack={() => setWizardStep(2)} onStart={() => setWizardStep(4)} loading={loading} />
      )}

      {step === "upload" && wizardOpen && wizardStep === 4 && uploadedDataset && <PreRunReview question={roughPrompt} objectives={analysisObjectives} model={uploadedDataset} onBack={() => setWizardStep(3)} onStart={startPipeline} loading={loading} />}

      {step === "running" && (
        <div style={panelStyle}>
          <span className="mono" style={{ color: "var(--teal)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.07em" }}>{sessionData?.status || "running"} · attempt {sessionData?.run_attempt || 1}</span>
          <h2 style={{ fontSize: 20, margin: "12px 0 8px" }}>Working through the {stage} phase</h2>
          <p style={{ color: "var(--muted)", lineHeight: 1.6 }}>Your run is saved in PostgreSQL. You may leave this page and reopen it from Recent analyses without losing its state.</p>
          <div style={{ height: 5, borderRadius: 99, overflow: "hidden", background: "var(--border)", marginTop: 20 }}><div style={{ width: "42%", height: "100%", background: "var(--teal)", animation: "pulse 1.4s ease-in-out infinite" }} /></div>
        </div>
      )}

      {step === "checkpoint" && checkpoint && (
        <div style={{ ...panelStyle, borderColor: "var(--amber)" }}>
          <span className="mono" style={{ fontSize: 11, color: "var(--amber)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Needs your input · {checkpoint.stage}</span>
          <h2 style={{ fontSize: 18, marginTop: 12, marginBottom: 18, fontWeight: 500, lineHeight: 1.5, whiteSpace: "pre-line" }}>{checkpoint.question}</h2>
          {checkpoint.stage === "deliverables" ? <DeliverablePicker selected={requestedOutputs} onChange={setRequestedOutputs} loading={loading} submit={submitAnswer} /> : <><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} rows={3} autoFocus style={textareaStyle} /><button onClick={submitAnswer} disabled={loading || !answer.trim()} style={{ ...primaryButton, background: "var(--amber)", opacity: loading || !answer.trim() ? 0.5 : 1 }}>{loading ? "Saving answer…" : "Continue analysis"}</button></>}
        </div>
      )}

      {step === "error" && (
        <div style={panelStyle}>
          <span className="mono" style={{ color: "var(--danger)", fontSize: 11, textTransform: "uppercase" }}>Run stopped safely</span>
          <h2 style={{ fontSize: 20, margin: "12px 0 8px" }}>The last checkpoint is still available</h2>
          <p style={{ color: "var(--muted)", lineHeight: 1.6 }}>Retry continues from durable LangGraph state. Completed workflow steps are not intentionally repeated.</p>
          <button onClick={retryAnalysis} disabled={loading} style={primaryButton}>{loading ? "Retrying…" : "Retry from checkpoint"}</button>
        </div>
      )}

      {step === "report" && sessionData && <ReportView sessionData={sessionData} />}
    </main>
  );
}

function DateRangeFields({ start, end, setStart, setEnd }) {
  return <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}><div><label style={labelStyle}>Start date</label><input value={start} onChange={(event) => setStart(event.target.value)} placeholder="28daysAgo or 2026-08-01" style={{ ...textareaStyle, minHeight: 42 }} /></div><div><label style={labelStyle}>End date</label><input value={end} onChange={(event) => setEnd(event.target.value)} placeholder="yesterday or 2026-08-07" style={{ ...textareaStyle, minHeight: 42 }} /></div></div>;
}

function DeliverablePicker({ selected, onChange, loading, submit }) {
  const options = [["executive_report", "Executive report"], ["professional_case_study", "Professional case study"], ["technical_report", "Technical report"], ["presentation", "PowerPoint presentation"], ["project_zip", "Project ZIP"]];
  function toggle(id) { onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]); }
  return <div><p style={{ color: "var(--muted)", marginBottom: 12 }}>Select only what you need. You can also continue with the on-screen analysis and create no document.</p><div className="objective-grid">{options.map(([id, label]) => <button key={id} type="button" onClick={() => toggle(id)} className={selected.includes(id) ? "selected" : ""}><span>{selected.includes(id) ? "✓" : "+"}</span>{label}</button>)}</div><button onClick={() => submit(JSON.stringify({ requested_outputs: selected }))} disabled={loading} style={{ ...primaryButton, background: "var(--amber)", marginTop: 14 }}>{loading ? "Creating selected deliverables…" : selected.length ? "Create selected deliverables" : "Continue without documents"}</button></div>;
}

function WizardProgress({ current }) {
  const steps = [[1,"Decision"],[2,"Data"],[3,"Model"],[4,"Review"]];
  return <div className="wizard-progress" aria-label="New analysis progress">{steps.map(([number,label]) => <div key={number} className={number === current ? "active" : number < current ? "complete" : ""}><span>{number < current ? "✓" : number}</span><strong>{label}</strong></div>)}</div>;
}

function ProjectDashboard({ sessions, allSessions, evaluation, search, onSearch, filter, onFilter, onNew, onOpen, onRunEvaluation, evaluationRunning }) {
  const summary = evaluationSummary(evaluation);
  const complete = allSessions.filter((item) => item.status === "complete").length;
  const active = allSessions.filter((item) => ["queued","running","active","paused_for_input"].includes(item.status)).length;
  return <div className="project-dashboard">
    <section className="dashboard-hero">
      <div><span className="mono">Project command center</span><h2>Turn evidence into decisions</h2><p>Create a governed analysis, return to work in progress, or open a completed decision package.</p></div>
      <button onClick={onNew} style={primaryButton}>+ New analysis</button>
    </section>
    <section className="dashboard-metrics">
      <article><span>All projects</span><strong>{allSessions.length}</strong><small>Durable analyses</small></article>
      <article><span>Active work</span><strong>{active}</strong><small>Running or awaiting input</small></article>
      <article><span>Completed</span><strong>{complete}</strong><small>Decision packages ready</small></article>
      <article className={summary?.release_ready ? "healthy" : "attention"}><span>Release gate</span><strong>{summary ? `${summary.passed_count}/${summary.case_count}` : "—"}</strong><small>{summary?.release_ready ? "All checks passed" : "Needs verification"}</small></article>
    </section>
    <div className="dashboard-toolbar"><input aria-label="Search projects" value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search projects…" /><div>{[["all","All"],["running","Running"],["paused_for_input","Needs input"],["complete","Complete"],["error","Errors"]].map(([id,label]) => <button key={id} onClick={() => onFilter(id)} className={filter === id ? "active" : ""}>{label}</button>)}</div></div>
    <section className="project-list-section">
      <div className="section-heading"><div><span className="mono">Projects</span><h3>{filter === "all" ? "Recent analysis projects" : `${filter.replaceAll("_"," ")} projects`}</h3></div><span>{sessions.length} shown</span></div>
      {sessions.length ? <div className="project-card-grid">{sessions.map((session) => <button key={session.session_id} onClick={() => onOpen(session.session_id)} className="project-card"><div className="project-card-top"><span className={`project-status ${session.status}`}>{session.status.replaceAll("_"," ")}</span><small>{formatDate(session.updated_at)}</small></div><strong>{session.business_task || `Analysis ${session.session_id.slice(0,8)}`}</strong><p>{session.status === "complete" ? "Report and deliverables available" : session.status === "paused_for_input" ? "Your input is required to continue" : session.status === "error" ? "Stopped safely · retry available" : `Currently in ${session.current_stage || "ask"} phase`}</p><div className="project-open">Open project <span>→</span></div></button>)}</div> : <div className="empty-projects"><strong>{allSessions.length ? "No projects match this view" : "Your first decision project starts here"}</strong><p>{allSessions.length ? "Try a different search or status filter." : "Define a business question, connect evidence, and let the agent build an auditable decision package."}</p>{!allSessions.length && <button onClick={onNew} style={primaryButton}>Create first analysis</button>}</div>}
    </section>
    <EvaluationPanel evaluation={evaluation} running={evaluationRunning} onRun={onRunEvaluation} />
  </div>;
}

function PreRunReview({ question, objectives, model, onBack, onStart, loading }) {
  const sources = model.datasets || [];
  const joins = model.proposed_joins || [];
  return <div style={panelStyle}>
    <span className="mono wizard-kicker">Step 4 · Final review</span><h2 className="wizard-title">Confirm the analysis contract</h2><p className="wizard-copy">This is exactly what the agent will analyze and produce. The Ask phase will still let you refine the task before calculations begin.</p>
    <div className="preflight-grid"><article><span>Decision question</span><strong>{question}</strong></article><article><span>Analytical objectives</span><div className="review-tags">{objectives.map((item) => <b key={item}>{item}</b>)}</div></article><article><span>Approved evidence</span><strong>{sources.length} source{sources.length === 1 ? "" : "s"} · {joins.length} join{joins.length === 1 ? "" : "s"}</strong><small>{sources.map((item) => item.filename).join(" · ")}</small></article><article><span>Deliverables</span><strong>Case study · Presentation · Project files</strong><small>Editable report, PowerPoint, notebook, code, charts, cleaned data, and audit trail</small></article></div>
    <div className="preflight-notice"><strong>Human checkpoints remain active</strong><p>You will approve the business task, source credibility, and analysis plan before the agent completes the work.</p></div>
    <div className="wizard-actions"><button onClick={onBack} style={secondaryButton}>Back to model</button><button onClick={onStart} disabled={loading} style={{ ...primaryButton, opacity: loading ? .5 : 1 }}>{loading ? "Creating project…" : "Create project and start"}</button></div>
  </div>;
}

function evaluationSummary(evaluation) {
  return evaluation?.summary || (evaluation?.weighted_score != null ? evaluation : null);
}

function EvaluationBadge({ evaluation }) {
  const summary = evaluationSummary(evaluation);
  if (!summary) return <span className="evaluation-badge idle">Accuracy not evaluated</span>;
  return <span className={`evaluation-badge ${summary.release_ready ? "ready" : "blocked"}`}>{summary.release_ready ? "Release ready" : "Release blocked"} · {(summary.weighted_score * 100).toFixed(0)}%</span>;
}

function EvaluationPanel({ evaluation, running, onRun }) {
  const summary = evaluationSummary(evaluation);
  const categories = summary?.category_scores || {};
  const rootCauseGate = summary?.root_cause_gate;
  return (
    <section className="evaluation-panel">
      <div>
        <span className="mono evaluation-kicker">Accuracy & regression gate</span>
        <h2>{summary ? `${summary.passed_count}/${summary.case_count} deterministic cases passed` : "No release evaluation recorded"}</h2>
        <p>{summary ? "Calculations, data handling, uncertainty, causal safety, root-cause diagnosis, repeatability, and real browser journeys are checked before release." : "Run the versioned evaluation suites before relying on a new release."}</p>
      </div>
      {summary && <div className="evaluation-categories">{Object.entries(categories).map(([name, score]) => <span key={name}><strong>{(score * 100).toFixed(0)}%</strong>{name.replace("_", " ")}</span>)}</div>}
      {rootCauseGate?.metric_scores && <div className="evaluation-categories">{Object.entries(rootCauseGate.metric_scores).map(([name, score]) => <span key={`rca-${name}`}><strong>{(score * 100).toFixed(0)}%</strong>{`RCA ${name.replaceAll("_", " ")}`}</span>)}</div>}
      <button onClick={onRun} disabled={running} style={secondaryButton}>{running ? "Running analytics and RCA cases…" : summary ? "Run evaluation again" : "Run accuracy evaluation"}</button>
    </section>
  );
}

function DatasetReview({ dataset, onBack, onStart, loading }) {
  const sources = dataset.datasets || [];
  const relationships = dataset.relationships || [];
  const approved = new Set((dataset.proposed_joins || []).map((item) => item.relationship_id));
  const ready = sources.length === 1 || (dataset.model_status === "ready" && approved.size === sources.length - 1);
  return (
    <div style={panelStyle}>
      <span className="mono" style={{ color: "var(--teal)", fontSize: 11, textTransform: "uppercase" }}>Data model review</span>
      <h2 style={{ fontSize: 21, margin: "10px 0 6px" }}>{sources.length === 1 ? sources[0].filename : `${sources.length} connected data sources`}</h2>
      <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 20 }}>Review file grain, join keys, match coverage, and row-multiplication risk before analysis.</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginBottom: 22 }}>
        <MetricCard value={sources.length} label="Sources" />
        <MetricCard value={relationships.length} label="Relationships checked" />
        <MetricCard value={approved.size} label="Approved joins" />
      </div>
      {!ready && <div className="model-warning"><strong>Model needs review</strong><p>The selected files cannot yet be connected through safe, high-confidence keys. Rename matching keys or remove the unconnected file; the agent will not guess.</p></div>}
      <Section title="Source register">
        <div className="source-card-grid">{sources.map((source) => <article key={source.dataset_id} className="source-card"><div><strong>{source.filename}</strong><span>{source.rows} rows · {source.columns} columns</span></div><small>Candidate keys: {source.candidate_keys.length ? source.candidate_keys.join(", ") : "None confirmed"}</small><details><summary>View quality profile</summary><div className="source-quality">Duplicates: {source.profile.duplicate_row_count} · All-null fields: {source.profile.all_null_columns.length} · Constant fields: {source.profile.constant_columns.length}</div></details></article>)}</div>
      </Section>
      {sources.length > 1 && <Section title="Relationship intelligence"><div className="relationship-list">{relationships.length ? relationships.map((item) => <article key={item.relationship_id} className={`relationship-card ${item.blocked ? "blocked" : approved.has(item.relationship_id) ? "approved" : ""}`}><div className="relationship-title"><strong>{item.left_filename}</strong><span>{item.left_key}</span><b>→</b><strong>{item.right_filename}</strong><span>{item.right_key}</span></div><div className="relationship-metrics"><span>{item.cardinality.replaceAll("_", " ")}</span><span>{(item.left_match_rate * 100).toFixed(0)}% left coverage</span><span>{(item.right_match_rate * 100).toFixed(0)}% right coverage</span><span>{(item.confidence_score * 100).toFixed(0)}% confidence</span></div><div className="relationship-status">{item.blocked ? "Blocked — row multiplication risk" : approved.has(item.relationship_id) ? "Approved for model" : "Detected, not selected"}</div>{item.warnings.length > 0 && <ul>{item.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}</article>) : <p className="muted">No compatible shared keys were detected.</p>}</div></Section>}
      <div style={{ display: "flex", gap: 10 }}><button onClick={onBack} style={secondaryButton}>Choose files again</button><button onClick={onStart} disabled={loading || !ready} style={{ ...primaryButton, opacity: loading || !ready ? .5 : 1 }}>{loading ? "Building approved model…" : sources.length > 1 ? "Approve model and continue" : "Approve dataset and continue"}</button></div>
    </div>
  );
}

function MetricCard({ value, label }) {
  return <div style={{ padding: 14, border: "1px solid var(--border)", borderRadius: 9, background: "var(--panel-raised)" }}><div style={{ fontSize: 22, fontWeight: 700 }}>{value ?? "—"}</div><div className="mono" style={{ color: "var(--muted)", fontSize: 10, textTransform: "uppercase" }}>{label}</div></div>;
}

function RecentSessions({ sessions, onOpen }) {
  if (!sessions.length) return null;
  return (
    <section style={{ marginTop: 30 }}>
      <h2 style={{ fontSize: 13, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 10 }}>Recent analyses</h2>
      <div style={{ display: "grid", gap: 8 }}>
        {sessions.map((session) => (
          <button key={session.session_id} onClick={() => onOpen(session.session_id)} style={{ ...panelStyle, padding: 14, cursor: "pointer", textAlign: "left", color: "var(--text)", display: "flex", justifyContent: "space-between", gap: 16 }}>
            <span><strong style={{ display: "block", fontSize: 13 }}>{session.business_task || `Analysis ${session.session_id.slice(0, 8)}`}</strong><span style={{ color: "var(--muted)", fontSize: 11 }}>{formatDate(session.updated_at)}</span></span>
            <span className="mono" style={{ color: session.status === "complete" ? "var(--teal)" : session.status === "error" ? "var(--danger)" : "var(--amber)", fontSize: 11 }}>{session.status}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ReleaseReadiness({ result }) {
  const gates = result?.quality_gates || [];
  if (!gates.length) return null;
  const criticalFailures = gates.filter((item) => item.status !== "Pass" && item.severity === "critical");
  const advisories = gates.filter((item) => item.status !== "Pass" && item.severity !== "critical");
  const passed = gates.filter((item) => item.status === "Pass").length;
  const readiness = criticalFailures.length ? "Needs revision" : advisories.length ? "Ready with advisory" : "Ready to share";
  const tone = criticalFailures.length ? "danger" : advisories.length ? "warning" : "ready";

  return (
    <Section title="Release readiness">
      <div className={`readiness-panel ${tone}`}>
        <div>
          <div className="readiness-label">{readiness}</div>
          <div className="readiness-copy">{criticalFailures.length ? "A critical publication check needs attention before this work is shared." : advisories.length ? "The analysis passed all critical checks; review the advisory before distribution." : "The analysis passed every publication check and is ready for stakeholder review."}</div>
        </div>
        <div className="readiness-stats">
          <div><strong>{passed}/{gates.length}</strong><span>checks passed</span></div>
          <div><strong>{result.validation_status || "Unknown"}</strong><span>data validation</span></div>
          <div><strong>{result.evidence?.length || 0}</strong><span>evidence records</span></div>
        </div>
      </div>
      <details className="quality-details">
        <summary>Review publication checks</summary>
        <div className="quality-list">{gates.map((gate) => <div key={gate.gate_id} className="quality-row"><span className={`quality-status ${gate.status === "Pass" ? "pass" : "fail"}`}>{gate.status === "Pass" ? "PASS" : gate.severity === "critical" ? "BLOCK" : "ADVISORY"}</span><span><strong>{gate.name}</strong><small>{gate.detail}</small></span></div>)}</div>
      </details>
    </Section>
  );
}

function ReportView({ sessionData }) {
  const result = sessionData.result;
  const [editingArtifact, setEditingArtifact] = useState(null);
  const presentationArtifacts = sessionData.artifacts.filter((item) => item.type === "presentation");
  const projectFileArtifacts = sessionData.artifacts.filter((item) => item.type === "project_files");
  return <ReportWorkspace sessionData={sessionData} />;

  /* Legacy continuous report retained temporarily for safe rollback. */
  return (
    <div style={panelStyle}>
      <span className="mono" style={{ fontSize: 11, color: "var(--teal)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Complete · evidence linked</span>
      <h2 style={{ fontSize: 20, marginTop: 10, marginBottom: 24 }}>{sessionData.business_task || "Analysis report"}</h2>
      {result ? (
        <>
          <Section title="Executive Summary"><NarrativeText text={result.summary} /></Section>
          <ReleaseReadiness result={result} />
          <Section title="Evidence-backed findings">
            {result.findings.map((finding) => <div key={finding.finding_id} style={{ background: "var(--panel-raised)", borderRadius: 8, padding: 16, marginBottom: 10 }}><div className="mono" style={{ color: "var(--teal)", fontSize: 11 }}>{finding.finding_id} · {finding.confidence} confidence</div><div style={{ marginTop: 7, fontWeight: 600 }}>{finding.statement}</div><div style={{ marginTop: 6, color: "var(--muted)", fontSize: 13 }}>{finding.implication}</div><div className="mono" style={{ marginTop: 8, color: "var(--muted)", fontSize: 11 }}>Evidence: {finding.evidence_ids.join(", ")}</div></div>)}
          </Section>
          <Section title="Recommended actions">
            {result.recommendations.map((item) => <div key={item.recommendation_id} style={{ borderLeft: "3px solid var(--amber)", paddingLeft: 14, marginBottom: 16 }}><div style={{ fontWeight: 600 }}>{item.action}</div><div style={{ marginTop: 5, color: "var(--muted)", fontSize: 13 }}>{item.rationale}</div><div className="mono" style={{ marginTop: 7, color: "var(--muted)", fontSize: 11 }}>{item.owner_role} · {item.timeframe} · Supports {item.finding_ids.join(", ")}</div></div>)}
          </Section>
          <Section title="Limitations"><ul style={{ paddingLeft: 20, color: "var(--muted)", lineHeight: 1.65 }}>{result.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></Section>
        </>
      ) : <p style={{ color: "var(--muted)" }}>The run completed without a result summary.</p>}

      <Section title="Professional deliverables"><div style={{ display: "grid", gap: 10 }}>{sessionData.artifacts.filter((item) => ["report", "documentation"].includes(item.type)).map((item) => <div key={item.id} style={{ padding: 16, background: "var(--panel-raised)", border: `1px solid ${editingArtifact?.id === item.id ? "var(--teal)" : "var(--border)"}`, borderRadius: 9 }}><strong>{item.title || "Analysis deliverable"}</strong>{item.description && <div style={{ marginTop: 5, color: "var(--muted)", fontSize: 12 }}>{item.description}</div>}<div style={{ display: "flex", gap: 8, marginTop: 12 }}><button onClick={() => setEditingArtifact(item)} style={smallButton}>Edit document</button><a href={`${API_BASE}${item.url}`} target="_blank" rel="noreferrer" style={{ ...smallButton, textDecoration: "none" }}>View original ↗</a></div></div>)}</div></Section>
      {editingArtifact && <DocumentEditor artifact={editingArtifact} onClose={() => setEditingArtifact(null)} />}
      {presentationArtifacts.length > 0 && <Section title="Stakeholder Presentation"><div style={{ display: "grid", gap: 10 }}>{presentationArtifacts.map((item) => <div key={item.id} className="deliverable-card"><div><strong>{item.title || "Stakeholder Presentation"}</strong><p>{item.description}</p></div><a href={`${API_BASE}${item.url}`} style={{ ...smallButton, textDecoration: "none" }}>{item.format === "pptx" ? "Download editable PowerPoint" : "Open slides"}</a></div>)}</div></Section>}
      {projectFileArtifacts.length > 0 && <Section title="Project Files"><div style={{ display: "grid", gap: 10 }}>{projectFileArtifacts.map((item) => <div key={item.id} className="deliverable-card"><div><strong>{item.title || "Project Files"}</strong><p>{item.description}</p></div><a href={`${API_BASE}${item.url}`} style={{ ...smallButton, textDecoration: "none" }}>Download ZIP</a></div>)}</div></Section>}
      <Section title="Evidence charts"><div style={{ display: "grid", gap: 14 }}>{sessionData.artifacts.filter((item) => item.type === "chart").map((item) => <figure key={item.id} style={{ margin: 0 }}><img src={`${API_BASE}${item.url}`} alt={item.alt_text || item.title || "Analysis chart"} style={{ width: "100%", borderRadius: 8, background: "white" }} /><figcaption style={{ marginTop: 7, color: "var(--muted)", fontSize: 12 }}><strong style={{ color: "var(--text)" }}>{item.title || "Analysis chart"}</strong>{item.chart_type && <span> · {item.chart_type}</span>}{item.evidence_id && <span> · {item.evidence_id}</span>}{item.subtitle && <div style={{ marginTop: 3 }}>{item.subtitle}</div>}</figcaption></figure>)}</div></Section>
      <details><summary style={{ color: "var(--muted)", cursor: "pointer", fontSize: 12 }}>Methodology and pipeline activity</summary><div style={{ marginTop: 12 }}>{sessionData.actions.map((action, index) => <div key={index} className="mono" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>[{action.stage}] {action.type}</div>)}</div></details>
    </div>
  );
}

function RootCauseInvestigation({ report, semantics }) {
  if (!report) return null;
  const conclusion = report.conclusion || {};
  const incident = report.incident || {};
  const reconciliation = report.reconciliation || {};
  const primary = (report.drivers || []).find((item) => item.driver_id === conclusion.primary_driver_id);
  const number = (value) => value == null ? "Not established" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return <>
    <Section title="Investigation conclusion">
      <div className={`readiness-panel ${conclusion.determination === "inconclusive" ? "warning" : "ready"}`}>
        <div><div className="readiness-label">{String(conclusion.determination || report.status || "inconclusive").replaceAll("_", " ")}</div><div className="readiness-copy">{conclusion.statement || "I cannot determine the root cause from the available evidence."}</div></div>
        <div className="readiness-stats"><div><strong>{conclusion.evidence_strength || "low"}</strong><span>evidence strength</span></div><div><strong>{conclusion.causal_claim_allowed ? "Yes" : "No"}</strong><span>causal claim allowed</span></div><div><strong>{primary?.name || "Not established"}</strong><span>primary mathematical driver</span></div></div>
      </div>
      {conclusion.abstention_reason && <div className="model-warning"><strong>Investigation boundary</strong><p>{conclusion.abstention_reason}</p></div>}
    </Section>
    {incident.metric && <Section title="Incident and baseline"><div className="preflight-grid"><article><span>Metric</span><strong>{incident.metric}</strong><small>{semantics?.metric?.expression || semantics?.message || "Approved operation definition"}</small></article><article><span>Baseline</span><strong>{number(incident.baseline_value)}</strong><small>{incident.baseline_period}</small></article><article><span>Comparison</span><strong>{number(incident.comparison_value)}</strong><small>{incident.comparison_period}</small></article><article><span>Observed movement</span><strong>{number(incident.absolute_change)}</strong><small>{incident.percent_change == null ? "Percentage change undefined" : `${number(incident.percent_change)}%`}</small></article></div></Section>}
    {report.data_health && <Section title="Data health"><div className="source-card"><div><strong>{String(report.data_health.status).toUpperCase()}</strong><span>{report.data_health.evidence_strength} evidence strength</span></div>{[...(report.data_health.blocking_failures || []), ...(report.data_health.cautions || [])].map((item) => <small key={item}>{item}</small>)}</div></Section>}
    {(report.drivers || []).length > 0 && <Section title="KPI decomposition and contribution"><div className="finding-grid">{report.drivers.map((driver) => <article key={driver.driver_id} className="finding-card"><div className="mono">{driver.driver_id} · {driver.evidence_strength} evidence</div><strong>{driver.name}</strong><p>{number(driver.absolute_change)} absolute change · {number(driver.contribution_to_total_change_pct)}% of observed movement</p><small>{driver.direction.replaceAll("_", " ")} · Evidence: {(driver.evidence_ids || []).join(", ")}</small></article>)}</div><div className="model-warning"><strong>Explained versus unexplained</strong><p>{reconciliation.note || "Reconciliation was not available."} Explained: {number(reconciliation.explained_change)} · Unexplained: {number(reconciliation.unexplained_change)}</p></div></Section>}
    <Section title="Hypotheses and falsification">{(report.hypotheses || []).length ? <div className="finding-grid">{report.hypotheses.map((item) => <article key={item.hypothesis_id} className="finding-card"><div className="mono">{item.hypothesis_id} · {item.status.replaceAll("_", " ")}</div><strong>{item.statement}</strong><p>{item.rationale}</p><small>Falsification: {(item.falsification_outcomes || []).join(", ") || "Not completed"}</small></article>)}</div> : <p className="muted">No mechanism hypothesis passed the typed evidence and falsification contract. This prevents a mathematical driver from being mislabeled as a causal root cause.</p>}</Section>
    <Section title="Next investigation"><ul className="limitation-list">{(report.next_investigations || []).map((item) => <li key={item}>{item}</li>)}</ul></Section>
    <Section title="Analysis trail"><div className="audit-log">{(report.analysis_trail || []).map((item, index) => <div key={item}><span>{String(index + 1).padStart(2,"0")}</span><div><strong>{item}</strong></div></div>)}</div></Section>
  </>;
}

function ReportWorkspace({ sessionData }) {
  const result = sessionData.result;
  const [activeTab, setActiveTab] = useState("overview");
  const [editingArtifact, setEditingArtifact] = useState(null);
  const documents = sessionData.artifacts.filter((item) => ["report", "documentation"].includes(item.type));
  const presentations = sessionData.artifacts.filter((item) => item.type === "presentation");
  const projectFiles = sessionData.artifacts.filter((item) => item.type === "project_files");
  const charts = sessionData.artifacts.filter((item) => item.type === "chart");
  const deliverableCount = documents.length + presentations.length + projectFiles.length;

  return <div style={panelStyle}>
    <div className="report-heading"><div><span className="mono report-status">Complete · evidence linked</span><h2>{sessionData.business_task || "Analysis report"}</h2></div><div className="report-facts"><span><strong>{result?.findings?.length || 0}</strong>findings</span><span><strong>{charts.length}</strong>visuals</span><span><strong>{deliverableCount}</strong>deliverables</span></div></div>
    <nav className="report-tabs" aria-label="Analysis result sections">{[["overview","Overview"], ...(result?.root_cause_report ? [["investigation","Investigation"]] : []), ["deliverables","Deliverables"],["evidence","Evidence"],["audit","Audit & limitations"]].map(([id,label]) => <button key={id} onClick={() => setActiveTab(id)} className={activeTab === id ? "active" : ""}>{label}</button>)}</nav>

    {activeTab === "overview" && (result ? <>
      <Section title="Executive Summary"><NarrativeText text={result.summary} /></Section>
      <ReleaseReadiness result={result} />
      <Section title="Evidence-backed findings"><div className="finding-grid">{result.findings.map((finding) => <article key={finding.finding_id} className="finding-card"><div className="mono">{finding.finding_id} · {finding.confidence} confidence</div><strong>{finding.statement}</strong><p>{finding.implication}</p><small>Evidence: {finding.evidence_ids.join(", ")}</small></article>)}</div></Section>
      <Section title="Recommended actions"><div className="action-grid">{result.recommendations.map((item) => <article key={item.recommendation_id}><strong>{item.action}</strong><p>{item.rationale}</p><small>{item.owner_role} · {item.timeframe} · Supports {item.finding_ids.join(", ")}</small></article>)}</div></Section>
    </> : <p className="muted">The run completed without a result summary.</p>)}

    {activeTab === "deliverables" && <>
      <Section title="Editable case study report"><div className="deliverables-grid">{documents.map((item) => <div key={item.id} className="deliverable-card"><div><strong>{item.title || "Analysis deliverable"}</strong><p>{item.description}</p></div><div className="deliverable-actions"><button onClick={() => setEditingArtifact(item)} style={smallButton}>Edit document</button><a href={`${API_BASE}${item.url}`} target="_blank" rel="noreferrer" style={{ ...smallButton, textDecoration:"none" }}>View original ↗</a></div></div>)}</div></Section>
      {editingArtifact && <DocumentEditor artifact={editingArtifact} onClose={() => setEditingArtifact(null)} />}
      {presentations.length > 0 && <Section title="Stakeholder presentation"><div className="deliverables-grid">{presentations.map((item) => <div key={item.id} className="deliverable-card"><div><strong>{item.title || "Stakeholder Presentation"}</strong><p>{item.description}</p></div><a href={`${API_BASE}${item.url}`} style={{ ...smallButton, textDecoration:"none" }}>Download PowerPoint</a></div>)}</div></Section>}
      {projectFiles.length > 0 && <Section title="Reproducible project files"><div className="deliverables-grid">{projectFiles.map((item) => <div key={item.id} className="deliverable-card"><div><strong>{item.title || "Project Files"}</strong><p>{item.description}</p></div><a href={`${API_BASE}${item.url}`} style={{ ...smallButton, textDecoration:"none" }}>Download ZIP</a></div>)}</div></Section>}
    </>}

    {activeTab === "investigation" && <RootCauseInvestigation report={result?.root_cause_report} semantics={result?.metric_semantics} />}

    {activeTab === "evidence" && <Section title="Evidence charts"><div className="chart-grid">{charts.map((item) => <figure key={item.id}><img src={`${API_BASE}${item.url}`} alt={item.alt_text || item.title || "Analysis chart"} /><figcaption><strong>{item.title || "Analysis chart"}</strong>{item.chart_type && <span> · {item.chart_type}</span>}{item.evidence_id && <span> · {item.evidence_id}</span>}{item.subtitle && <div>{item.subtitle}</div>}</figcaption></figure>)}</div></Section>}

    {activeTab === "audit" && <>
      {result && <Section title="Limitations and interpretation boundaries"><ul className="limitation-list">{result.limitations.map((item,index) => <li key={index}>{item}</li>)}</ul></Section>}
      <Section title="Methodology and pipeline activity"><div className="audit-log">{sessionData.actions.map((action,index) => <div key={index}><span>{String(index + 1).padStart(2,"0")}</span><div><strong>{action.stage}</strong><small>{action.type.replaceAll("_"," ")}</small></div></div>)}</div></Section>
    </>}
  </div>;
}

function DocumentEditor({ artifact, onClose }) {
  const [draft, setDraft] = useState(null);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState("Loading editable document…");

  useEffect(() => {
    let cancelled = false;
    setDraft(null);
    setMessage("Loading editable document…");
    requestJson(`${API_BASE}/artifacts/${artifact.id}/editor`)
      .then((data) => {
        if (!cancelled) {
          setDraft(data.content);
          setVersion(data.version);
          setDirty(false);
          setMessage(data.version ? `Saved revision ${data.version}` : "Original AI draft · not edited yet");
        }
      })
      .catch((loadError) => !cancelled && setMessage(loadError.message));
    return () => { cancelled = true; };
  }, [artifact.id]);

  function updateDocument(field, value) {
    setDraft((current) => ({ ...current, [field]: value }));
    setDirty(true);
    setMessage("Ready to save");
  }

  function updateSection(index, field, value) {
    setDraft((current) => ({ ...current, sections: current.sections.map((section, sectionIndex) => sectionIndex === index ? { ...section, [field]: value } : section) }));
    setDirty(true);
    setMessage("Ready to save");
  }

  function updateBlock(sectionIndex, blockIndex, updater) {
    setDraft((current) => ({
      ...current,
      sections: current.sections.map((section, currentSectionIndex) => currentSectionIndex !== sectionIndex ? section : {
        ...section,
        blocks: (section.blocks || []).map((block, currentBlockIndex) => currentBlockIndex === blockIndex ? updater(block) : block),
      }),
    }));
    setDirty(true);
    setMessage("Ready to save");
  }

  function addBlock(sectionIndex, type) {
    const block = type === "table"
      ? { type: "table", title: "New table", columns: ["Column 1", "Column 2"], rows: [["", ""]], text: "", items: [] }
      : type === "bullets"
        ? { type: "bullets", title: "New list", items: ["Add an item"], text: "", columns: [], rows: [] }
        : { type: "prose", title: "New narrative", text: "Add your content here.", items: [], columns: [], rows: [] };
    setDraft((current) => ({ ...current, sections: current.sections.map((section, index) => index === sectionIndex ? { ...section, blocks: [...(section.blocks || []), block] } : section) }));
    setDirty(true);
    setMessage("Ready to save");
  }

  function removeBlock(sectionIndex, blockIndex) {
    setDraft((current) => ({ ...current, sections: current.sections.map((section, index) => index === sectionIndex ? { ...section, blocks: (section.blocks || []).filter((_, itemIndex) => itemIndex !== blockIndex) } : section) }));
    setDirty(true);
    setMessage("Ready to save");
  }

  async function saveDocument() {
    setBusy(true);
    setMessage("Saving revision…");
    try {
      const saved = await requestJson(`${API_BASE}/artifacts/${artifact.id}/editor`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_version: version, content: draft }),
      });
      setVersion(saved.version);
      setDraft(saved.content);
      setDirty(false);
      setMessage(`Revision ${saved.version} saved`);
      return true;
    } catch (saveError) {
      setMessage(saveError.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function downloadWord() {
    if (dirty && !(await saveDocument())) return;
    window.open(`${API_BASE}/artifacts/${artifact.id}/download.docx`, "_blank", "noopener,noreferrer");
  }

  async function downloadPdf() {
    if (dirty && !(await saveDocument())) return;
    window.open(`${API_BASE}/artifacts/${artifact.id}/download.pdf`, "_blank", "noopener,noreferrer");
  }

  function addSection() {
    setDraft((current) => ({ ...current, sections: [...current.sections, { heading: "New section", body: "", phase: null, blocks: [{ type: "prose", title: "Narrative", text: "Add your content here.", items: [], columns: [], rows: [] }] }] }));
    setDirty(true);
    setMessage("Ready to save");
  }

  function removeSection(index) {
    if (draft.sections.length <= 1) return;
    setDraft((current) => ({ ...current, sections: current.sections.filter((_, sectionIndex) => sectionIndex !== index) }));
    setDirty(true);
    setMessage("Ready to save");
  }

  return (
    <section style={{ border: "1px solid var(--teal)", borderRadius: 12, padding: 20, marginBottom: 26, background: "rgba(61,220,151,.035)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 14, alignItems: "flex-start", marginBottom: 18 }}><div><span className="mono" style={{ color: "var(--teal)", fontSize: 10, textTransform: "uppercase" }}>Editable documentation workspace</span><h3 style={{ fontSize: 17, marginTop: 5 }}>{artifact.title}</h3><div style={{ color: dirty ? "var(--amber)" : "var(--muted)", fontSize: 11, marginTop: 4 }}>{dirty ? `Unsaved changes · ${message}` : message}</div></div><button onClick={onClose} style={secondaryButton}>Close</button></div>
      {!draft ? <p style={{ color: "var(--muted)" }}>{message}</p> : <>
        <label style={labelStyle}>Document title</label><input value={draft.title} onChange={(event) => updateDocument("title", event.target.value)} style={inputStyle} />
        <label style={labelStyle}>Subtitle</label><textarea value={draft.subtitle} onChange={(event) => updateDocument("subtitle", event.target.value)} rows={2} style={textareaStyle} />
        {draft.sections.map((section, index) => <div key={index} style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 9, padding: 14, marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}><label style={labelStyle}>{section.phase ? `${section.phase} phase` : `Section ${index + 1}`}</label><button onClick={() => removeSection(index)} disabled={draft.sections.length <= 1} style={{ ...textButton, opacity: draft.sections.length <= 1 ? .35 : 1 }}>Remove section</button></div>
          <input aria-label={`Section ${index + 1} heading`} value={section.heading} onChange={(event) => updateSection(index, "heading", event.target.value)} style={inputStyle} />
          {(section.body || !(section.blocks || []).length) && <><label style={labelStyle}>Section narrative</label><textarea value={section.body || ""} onChange={(event) => updateSection(index, "body", event.target.value)} rows={Math.min(12, Math.max(3, (section.body || "").split("\n").length + 1))} style={textareaStyle} /></>}
          {(section.blocks || []).map((block, blockIndex) => <DocumentBlockEditor key={blockIndex} block={block} onChange={(updater) => updateBlock(index, blockIndex, updater)} onRemove={() => removeBlock(index, blockIndex)} />)}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 10 }}><button onClick={() => addBlock(index, "prose")} style={smallButton}>+ Narrative</button><button onClick={() => addBlock(index, "bullets")} style={smallButton}>+ List</button><button onClick={() => addBlock(index, "table")} style={smallButton}>+ Table</button></div>
        </div>)}
        <button onClick={addSection} style={secondaryButton}>+ Add section</button>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 9, alignItems: "center", marginTop: 18 }}><button onClick={saveDocument} disabled={busy || !dirty} style={{ ...primaryButton, opacity: busy || !dirty ? .45 : 1 }}>{busy ? "Saving…" : "Save revision"}</button><button onClick={downloadWord} disabled={busy} style={secondaryButton}>Download editable Word</button><button onClick={downloadPdf} disabled={busy} style={secondaryButton}>Download PDF</button><span style={{ color: "var(--muted)", fontSize: 11 }}>Version {version} · tables, narrative, and lists stay editable in Word</span></div>
      </>}
    </section>
  );
}

function DocumentBlockEditor({ block, onChange, onRemove }) {
  const updateField = (field, value) => onChange((current) => ({ ...current, [field]: value }));
  const updateColumn = (columnIndex, value) => onChange((current) => ({ ...current, columns: current.columns.map((column, index) => index === columnIndex ? value : column) }));
  const updateCell = (rowIndex, columnIndex, value) => onChange((current) => ({ ...current, rows: current.rows.map((row, index) => index === rowIndex ? row.map((cell, cellIndex) => cellIndex === columnIndex ? value : cell) : row) }));
  const addRow = () => onChange((current) => ({ ...current, rows: [...current.rows, current.columns.map(() => "")] }));
  const removeRow = (rowIndex) => onChange((current) => ({ ...current, rows: current.rows.filter((_, index) => index !== rowIndex) }));

  return <div style={{ background: "var(--panel-raised)", border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginTop: 10 }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}><span className="mono" style={{ color: "var(--teal)", fontSize: 9, textTransform: "uppercase" }}>{block.type}</span><button onClick={onRemove} style={textButton}>Remove block</button></div>
    <input aria-label="Block title" value={block.title || ""} onChange={(event) => updateField("title", event.target.value)} placeholder="Block title" style={{ ...inputStyle, marginTop: 8 }} />
    {block.type === "prose" && <textarea aria-label={`${block.title || "Narrative"} content`} value={block.text || ""} onChange={(event) => updateField("text", event.target.value)} rows={Math.min(14, Math.max(4, (block.text || "").split("\n").length + 1))} style={{ ...textareaStyle, marginBottom: 0 }} />}
    {block.type === "bullets" && <textarea aria-label={`${block.title || "List"} items`} value={(block.items || []).join("\n")} onChange={(event) => updateField("items", event.target.value.split("\n"))} rows={Math.min(14, Math.max(4, (block.items || []).length + 1))} style={{ ...textareaStyle, marginBottom: 0 }} />}
    {block.type === "table" && <div style={{ overflowX: "auto" }}>
      <table className="document-edit-table"><thead><tr>{(block.columns || []).map((column, columnIndex) => <th key={columnIndex}><input aria-label={`Column ${columnIndex + 1} heading`} value={column} onChange={(event) => updateColumn(columnIndex, event.target.value)} /></th>)}<th aria-label="Row actions" /></tr></thead>
        <tbody>{(block.rows || []).map((row, rowIndex) => <tr key={rowIndex}>{(block.columns || []).map((_, columnIndex) => <td key={columnIndex}><textarea aria-label={`Row ${rowIndex + 1}, column ${columnIndex + 1}`} value={row[columnIndex] || ""} onChange={(event) => updateCell(rowIndex, columnIndex, event.target.value)} rows={2} /></td>)}<td><button onClick={() => removeRow(rowIndex)} style={textButton}>Remove</button></td></tr>)}</tbody></table>
      <button onClick={addRow} style={{ ...smallButton, marginTop: 8 }}>+ Add row</button>
    </div>}
  </div>;
}

function Section({ title, children }) {
  return <section style={{ marginBottom: 24 }}><h3 style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>{title}</h3>{children}</section>;
}

function NarrativeText({ text }) {
  const blocks = String(text || "").replaceAll("**", "").replaceAll("`", "").split(/\n{2,}/).map((item) => item.trim()).filter(Boolean);
  return <div className="executive-copy">{blocks.map((block, index) => {
    const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
    if (lines.every((line) => /^[-*]\s+/.test(line))) return <ul key={index}>{lines.map((line, lineIndex) => <li key={lineIndex}>{line.replace(/^[-*]\s+/, "")}</li>)}</ul>;
    if (lines.every((line) => /^\d+\.\s+/.test(line))) return <ol key={index}>{lines.map((line, lineIndex) => <li key={lineIndex}>{line.replace(/^\d+\.\s+/, "")}</li>)}</ol>;
    if (/^#{1,6}\s+/.test(block)) return <h4 key={index}>{block.replace(/^#{1,6}\s+/, "")}</h4>;
    return <p key={index}>{lines.join(" ").replace(/^---\s*/, "")}</p>;
  })}</div>;
}

const panelStyle = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 28 };
const labelStyle = { display: "block", fontSize: 13, color: "var(--muted)", marginBottom: 7 };
const textareaStyle = { width: "100%", padding: "11px 12px", background: "var(--panel-raised)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontSize: 14, marginBottom: 16, resize: "vertical" };
const inputStyle = { ...textareaStyle, resize: "none", marginBottom: 12 };
const primaryButton = { background: "var(--teal)", color: "var(--ink)", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 700, fontSize: 14, cursor: "pointer" };
const secondaryButton = { background: "transparent", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" };
const smallButton = { background: "transparent", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 7, padding: "7px 10px", fontWeight: 600, fontSize: 11, cursor: "pointer" };
const textButton = { background: "transparent", color: "var(--muted)", border: 0, padding: 0, fontSize: 11, cursor: "pointer" };
