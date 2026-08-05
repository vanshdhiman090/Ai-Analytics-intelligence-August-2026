"use client";

import { useState } from "react";
import PipelineTracker from "@/components/PipelineTracker";

const API_BASE = "http://localhost:8000";

export default function Home() {
  const [step, setStep] = useState("upload"); // upload | running | checkpoint | report
  const [filePath, setFilePath] = useState("/mnt/user-data/uploads/Nike_Dataset.csv");
  const [roughPrompt, setRoughPrompt] = useState("");
  const [businessQuestion, setBusinessQuestion] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [checkpoint, setCheckpoint] = useState(null);
  const [answer, setAnswer] = useState("");
  const [sessionData, setSessionData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function startPipeline() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: filePath, rough_prompt: roughPrompt, business_question: businessQuestion }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setSessionId(data.session_id);
      if (data.status === "paused_for_input") {
        setCheckpoint(data.checkpoint);
        setStep("checkpoint");
      } else {
        await loadReport(data.session_id);
      }
    } catch (e) {
      setError("Could not reach the analysis backend. Is it running on localhost:8000?");
    } finally {
      setLoading(false);
    }
  }

  async function submitAnswer() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/sessions/${sessionId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer }),
      });
      const data = await res.json();
      setAnswer("");
      if (data.status === "paused_for_input") {
        setCheckpoint(data.checkpoint);
      } else {
        await loadReport(sessionId);
      }
    } catch (e) {
      setError("Could not submit the answer — check the backend connection.");
    } finally {
      setLoading(false);
    }
  }

  async function loadReport(id) {
    const res = await fetch(`${API_BASE}/sessions/${id}`);
    const data = await res.json();
    setSessionData(data);
    setStep("report");
  }

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 24px" }}>
      <header style={{ marginBottom: 40 }}>
        <h1 style={{ fontSize: 28 }}>AI Analytics Workspace</h1>
        <p style={{ color: "var(--muted)", marginTop: 6 }}>
          Upload data. Confirm the question. Get a decision-ready report.
        </p>
      </header>

      {step !== "upload" && (
        <PipelineTracker
          currentStage={step === "report" ? "act" : step === "checkpoint" ? (checkpoint?.stage || "ask") : "ask"}
          status={step === "report" ? "complete" : "paused_for_input"}
        />
      )}

      {error && (
        <div style={{ background: "rgba(232,102,61,0.1)", border: "1px solid var(--danger)", borderRadius: 8, padding: 12, marginBottom: 20, color: "var(--danger)", fontSize: 14 }}>
          {error}
        </div>
      )}

      {step === "upload" && (
        <div style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 28 }}>
          <h2 style={{ fontSize: 16, marginBottom: 16 }}>Start a new analysis</h2>

          <label style={{ display: "block", fontSize: 13, color: "var(--muted)", marginBottom: 6 }}>Dataset path</label>
          <input
            value={filePath}
            onChange={(e) => setFilePath(e.target.value)}
            className="mono"
            style={{ width: "100%", padding: "10px 12px", background: "var(--panel-raised)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontSize: 13, marginBottom: 16 }}
          />

          <label style={{ display: "block", fontSize: 13, color: "var(--muted)", marginBottom: 6 }}>What do you want to know?</label>
          <textarea
            value={roughPrompt}
            onChange={(e) => setRoughPrompt(e.target.value)}
            placeholder="e.g. Which sales channel is losing the most margin, and why?"
            rows={3}
            style={{ width: "100%", padding: "10px 12px", background: "var(--panel-raised)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontSize: 14, marginBottom: 16, resize: "vertical" }}
          />

          <button
            onClick={startPipeline}
            disabled={loading || !roughPrompt}
            style={{ background: "var(--teal)", color: "var(--ink)", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 600, fontSize: 14, opacity: loading || !roughPrompt ? 0.5 : 1 }}
          >
            {loading ? "Starting…" : "Run analysis"}
          </button>
        </div>
      )}

      {step === "checkpoint" && checkpoint && (
        <div style={{ background: "var(--panel)", border: "1px solid var(--amber)", borderRadius: 12, padding: 28 }}>
          <span className="mono" style={{ fontSize: 11, color: "var(--amber)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Needs your input — {checkpoint.stage}
          </span>
          <h2 style={{ fontSize: 18, marginTop: 10, marginBottom: 18, fontWeight: 500, lineHeight: 1.4 }}>
            {checkpoint.question}
          </h2>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={2}
            autoFocus
            style={{ width: "100%", padding: "10px 12px", background: "var(--panel-raised)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontSize: 14, marginBottom: 16, resize: "vertical" }}
          />
          <button
            onClick={submitAnswer}
            disabled={loading || !answer}
            style={{ background: "var(--amber)", color: "var(--ink)", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 600, fontSize: 14, opacity: loading || !answer ? 0.5 : 1 }}
          >
            {loading ? "Submitting…" : "Continue"}
          </button>
        </div>
      )}

      {step === "report" && sessionData && (
        <div style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 28 }}>
          <span className="mono" style={{ fontSize: 11, color: "var(--teal)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Complete
          </span>
          <h2 style={{ fontSize: 18, marginTop: 10, marginBottom: 20 }}>{sessionData.business_task || "Analysis Report"}</h2>

          <Section title="Checkpoints answered">
            {sessionData.checkpoints.map((c, i) => (
              <div key={i} style={{ marginBottom: 10, fontSize: 13 }}>
                <div style={{ color: "var(--muted)" }}>{c.question}</div>
                <div className="mono" style={{ color: "var(--text)" }}>{c.answer}</div>
              </div>
            ))}
          </Section>

          <Section title="Pipeline log">
            {sessionData.actions.map((a, i) => (
              <div key={i} className="mono" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>
                [{a.stage}] {a.type}
              </div>
            ))}
          </Section>

          <Section title={`Artifacts (${sessionData.artifacts.length})`}>
            {sessionData.artifacts.map((a, i) => (
              <div key={i} className="mono" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>
                {a.type}: {a.path}
              </div>
            ))}
          </Section>
        </div>
      )}
    </main>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 22 }}>
      <h3 style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>{title}</h3>
      {children}
    </div>
  );
}
