"use client";

const STAGES = ["ask", "prepare", "process", "analyze", "share", "act"];

export default function PipelineTracker({ currentStage, status }) {
  const currentIndex = STAGES.indexOf(currentStage);

  return (
    <div style={{ display: "flex", alignItems: "center", padding: "24px 0" }}>
      {STAGES.map((stage, i) => {
        const isDone = i < currentIndex || (i === currentIndex && status === "complete");
        const isCurrent = i === currentIndex && status !== "complete";
        const isPaused = isCurrent && status === "paused_for_input";

        return (
          <div key={stage} style={{ display: "flex", alignItems: "center", flex: i < STAGES.length - 1 ? 1 : "none" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
              <div
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  background: isDone ? "var(--teal)" : isPaused ? "var(--amber)" : isCurrent ? "var(--panel-raised)" : "var(--panel)",
                  border: `2px solid ${isDone ? "var(--teal)" : isPaused ? "var(--amber)" : isCurrent ? "var(--text)" : "var(--border)"}`,
                  boxShadow: isPaused ? "0 0 0 6px rgba(232,163,61,0.15)" : isCurrent ? "0 0 0 6px rgba(232,236,243,0.08)" : "none",
                  transition: "all 0.3s ease",
                }}
              />
              <span
                className="mono"
                style={{
                  fontSize: 11,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: isDone ? "var(--teal)" : isPaused ? "var(--amber)" : isCurrent ? "var(--text)" : "var(--muted)",
                }}
              >
                {stage}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <div
                style={{
                  flex: 1,
                  height: 2,
                  background: isDone ? "var(--teal)" : "var(--border)",
                  marginBottom: 22,
                  transition: "background 0.3s ease",
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
