"use client";

import { useState } from "react";
import { buildInvestigationSummary, publicRcaResult } from "@/lib/rcaExport";

export default function ResultUtilities({ result }) {
  const [feedback, setFeedback] = useState("");

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(buildInvestigationSummary(result));
      setFeedback("Investigation summary copied.");
    } catch {
      setFeedback("Copy failed. Review and copy the visible result instead.");
    }
  }

  function downloadJson() {
    const blob = new Blob([JSON.stringify(publicRcaResult(result), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `rca-investigation-${result.investigation_id}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="result-utilities" aria-label="Investigation result utilities">
      <div className="button-row utility-actions">
        <button className="button secondary compact" type="button" onClick={copySummary}>Copy summary</button>
        <button className="button secondary compact" type="button" onClick={downloadJson}>Download public JSON</button>
      </div>
      <span className="utility-feedback" role="status" aria-live="polite">{feedback}</span>
    </div>
  );
}
