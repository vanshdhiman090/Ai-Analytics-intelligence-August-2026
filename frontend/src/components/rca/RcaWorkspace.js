"use client";

import { useEffect, useReducer, useRef } from "react";
import InvestigationResult from "@/components/rca/InvestigationResult";
import InvestigationSetup from "@/components/rca/InvestigationSetup";
import { ApiError, deleteDataset, runRcaInvestigation, uploadDataset } from "@/lib/api";
import { boundedGoal, titleize } from "@/lib/rcaPresentation";

const EMPTY_FORM = {
  kpiName: "",
  metricColumn: "",
  timeColumn: "",
  grain: "month",
  unit: "",
  baselinePeriod: "",
  comparisonPeriod: "",
  dimensions: [],
};

const INITIAL_STATE = {
  phase: "setup",
  dataset: null,
  form: EMPTY_FORM,
  fieldErrors: {},
  apiError: null,
  isUploading: false,
  isInvestigating: false,
  lastRequest: null,
  result: null,
};

function defaultForm(dataset) {
  const columns = Object.values(dataset?.profile?.columns || {});
  const allNull = new Set(dataset?.profile?.all_null_columns || []);
  const metric = columns.find((column) => column.semantic_type === "numeric" && !allNull.has(column.name));
  const time = columns.find((column) => column.semantic_type === "datetime" && column.date_semantics?.status !== "AMBIGUOUS_DATE_FORMAT");
  return {
    ...EMPTY_FORM,
    metricColumn: metric?.name || "",
    kpiName: metric?.name ? titleize(metric.name) : "",
    timeColumn: time?.name || "",
  };
}

function reducer(state, action) {
  switch (action.type) {
    case "UPLOAD_START":
      return { ...state, isUploading: true, apiError: null, fieldErrors: {} };
    case "UPLOAD_SUCCESS":
      return { ...state, phase: "configure", dataset: action.dataset, form: defaultForm(action.dataset), fieldErrors: {}, apiError: null, isUploading: false, result: null, lastRequest: null };
    case "UPLOAD_ERROR":
      return { ...state, isUploading: false, apiError: action.error, fieldErrors: action.fieldErrors || {} };
    case "SET_FIELD": {
      const form = { ...state.form, [action.field]: action.value };
      if (action.field === "grain") {
        form.baselinePeriod = "";
        form.comparisonPeriod = "";
      }
      if (["metricColumn", "timeColumn"].includes(action.field)) {
        form.dimensions = form.dimensions.filter((dimension) => ![form.metricColumn, form.timeColumn].includes(dimension));
      }
      return { ...state, form, fieldErrors: { ...state.fieldErrors, [action.field]: undefined }, apiError: null };
    }
    case "TOGGLE_DIMENSION": {
      const dimensions = state.form.dimensions.includes(action.dimension)
        ? state.form.dimensions.filter((item) => item !== action.dimension)
        : [...state.form.dimensions, action.dimension];
      return { ...state, form: { ...state.form, dimensions }, fieldErrors: { ...state.fieldErrors, dimensions: undefined }, apiError: null };
    }
    case "VALIDATION_ERROR":
      return { ...state, fieldErrors: action.errors, apiError: null };
    case "REVIEW":
      return { ...state, phase: "review", fieldErrors: {}, apiError: null };
    case "CONFIGURE":
      return { ...state, phase: "configure", apiError: null, result: action.keepResult ? state.result : null };
    case "INVESTIGATE_START":
      return { ...state, phase: "investigating", isInvestigating: true, apiError: null, fieldErrors: {}, lastRequest: action.payload };
    case "INVESTIGATE_SUCCESS":
      return { ...state, phase: "result", isInvestigating: false, apiError: null, result: action.result };
    case "INVESTIGATE_ERROR":
      return { ...state, phase: "configure", isInvestigating: false, apiError: action.error, fieldErrors: action.fieldErrors || {} };
    case "REMOVE_DATASET":
      return { ...INITIAL_STATE };
    case "RESET":
      return { ...INITIAL_STATE };
    default:
      return state;
  }
}

function validDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
}

function validPeriod(value, grain) {
  if (grain === "day") return validDate(value);
  if (grain === "week") return validDate(value) && new Date(`${value}T00:00:00Z`).getUTCDay() === 1;
  if (grain === "month") return /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
  if (grain === "quarter") return /^\d{4}Q[1-4]$/.test(value);
  return /^\d{4}$/.test(value) && Number(value) > 0;
}

function validate(dataset, form) {
  const errors = {};
  const columns = dataset?.profile?.columns || {};
  if (!dataset) errors.dataset = "Choose one CSV or Excel dataset.";
  if (!form.metricColumn) errors.metricColumn = "Select the numeric KPI column.";
  else if (!columns[form.metricColumn]) errors.metricColumn = "The selected KPI column is not in this dataset.";
  if (!form.kpiName.trim()) errors.kpiName = "Enter a clear KPI name.";
  if (!form.timeColumn) errors.timeColumn = "Select a safely parsed time column.";
  else if (!columns[form.timeColumn]) errors.timeColumn = "The selected time column is not in this dataset.";
  if (!validPeriod(form.baselinePeriod, form.grain)) errors.baselinePeriod = `Enter a valid canonical ${form.grain} period.`;
  if (!validPeriod(form.comparisonPeriod, form.grain)) errors.comparisonPeriod = `Enter a valid canonical ${form.grain} period.`;
  if (form.baselinePeriod && form.baselinePeriod === form.comparisonPeriod) errors.comparisonPeriod = "Comparison period must differ from baseline period.";
  if (!form.dimensions.length) errors.dimensions = "Select at least one candidate business dimension.";
  if (form.dimensions.length > 12) errors.dimensions = "Select no more than twelve candidate dimensions.";
  if (form.dimensions.some((dimension) => [form.metricColumn, form.timeColumn].includes(dimension))) errors.dimensions = "Metric and time columns cannot be candidate dimensions.";
  return errors;
}

function mapApiFields(error, form) {
  const mapped = {};
  for (const item of error.fields || []) {
    const field = item.field || "";
    if (field === "kpi.metric_column") mapped.metricColumn = error.message;
    else if (field === "kpi.time_column") mapped.timeColumn = error.message;
    else if (field === "kpi.name") mapped.kpiName = error.message;
    else if (field === "baseline_period") mapped.baselinePeriod = error.message;
    else if (field === "comparison_period") mapped.comparisonPeriod = error.message;
    else if (field === "candidate_dimensions" || field.startsWith("candidate_dimensions.")) mapped.dimensions = error.message;
    else if (field.startsWith("column:")) {
      const column = field.slice("column:".length);
      if (column === form.metricColumn) mapped.metricColumn = "This KPI column is no longer available in the uploaded dataset.";
      else if (column === form.timeColumn) mapped.timeColumn = "This time column is no longer available in the uploaded dataset.";
      else mapped.dimensions = `The selected dimension “${column}” is no longer available in the uploaded dataset.`;
    }
  }
  return mapped;
}

function ErrorBanner({ error }) {
  if (!error) return null;
  return (
    <div className="api-error" role="alert" tabIndex="-1">
      <div><strong>{error.code === "network_error" ? "Connection problem" : "The request needs attention"}</strong><p>{error.message}</p></div>
      {error.requestId && <small>Request ID: {error.requestId}</small>}
    </div>
  );
}

function LoadingPanel() {
  return (
    <section className="loading-panel" aria-live="polite" aria-busy="true">
      <div className="loading-mark" aria-hidden="true"><span /></div>
      <p className="eyebrow">Bounded investigation running</p>
      <h2>Testing the approved KPI movement</h2>
      <p>The service is validating data, testing the approved dimensions, reconciling signed movement, and compiling public evidence. This synchronous request does not expose live reasoning stages.</p>
    </section>
  );
}

export default function RcaWorkspace() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const resultRef = useRef(null);
  const errorRef = useRef(null);
  const investigationInFlightRef = useRef(false);

  useEffect(() => {
    if (state.phase === "result") resultRef.current?.focus();
  }, [state.phase]);

  useEffect(() => {
    if (state.apiError) errorRef.current?.querySelector("[role='alert']")?.focus();
  }, [state.apiError]);

  async function handleUpload(file) {
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      dispatch({ type: "UPLOAD_ERROR", error: new ApiError("Only CSV and Excel (.xlsx) files are supported."), fieldErrors: { dataset: "Choose a .csv or .xlsx file." } });
      return;
    }
    const previousDatasetId = state.dataset?.dataset_id;
    dispatch({ type: "UPLOAD_START" });
    try {
      const dataset = await uploadDataset(file);
      dispatch({ type: "UPLOAD_SUCCESS", dataset });
      if (previousDatasetId && previousDatasetId !== dataset.dataset_id) deleteDataset(previousDatasetId).catch(() => {});
    } catch (error) {
      dispatch({ type: "UPLOAD_ERROR", error, fieldErrors: state.dataset ? {} : { dataset: error.message } });
    }
  }

  async function handleRemoveDataset() {
    try {
      await deleteDataset(state.dataset?.dataset_id);
      dispatch({ type: "REMOVE_DATASET" });
    } catch (error) {
      dispatch({ type: "UPLOAD_ERROR", error, fieldErrors: {} });
    }
  }

  function handleReview() {
    const errors = validate(state.dataset, state.form);
    if (Object.keys(errors).length) {
      dispatch({ type: "VALIDATION_ERROR", errors });
      window.requestAnimationFrame(() => document.querySelector("[aria-invalid='true']")?.focus());
      return;
    }
    dispatch({ type: "REVIEW" });
  }

  async function handleRun() {
    if (investigationInFlightRef.current) return;
    const errors = validate(state.dataset, state.form);
    if (Object.keys(errors).length) {
      dispatch({ type: "VALIDATION_ERROR", errors });
      return;
    }
    const payload = {
      dataset_id: state.dataset.dataset_id,
      goal: boundedGoal(state.form),
      kpi: {
        name: state.form.kpiName.trim(),
        metric_column: state.form.metricColumn,
        time_column: state.form.timeColumn,
        time_grain: state.form.grain,
        aggregation: "sum",
        unit: state.form.unit.trim() || null,
      },
      baseline_period: state.form.baselinePeriod,
      comparison_period: state.form.comparisonPeriod,
      candidate_dimensions: state.form.dimensions,
    };
    investigationInFlightRef.current = true;
    dispatch({ type: "INVESTIGATE_START", payload });
    try {
      const result = await runRcaInvestigation(payload);
      dispatch({ type: "INVESTIGATE_SUCCESS", result });
    } catch (error) {
      dispatch({ type: "INVESTIGATE_ERROR", error, fieldErrors: mapApiFields(error, state.form) });
    } finally {
      investigationInFlightRef.current = false;
    }
  }

  async function handleNew() {
    const datasetId = state.dataset?.dataset_id;
    dispatch({ type: "RESET" });
    if (datasetId) deleteDataset(datasetId).catch(() => {});
  }

  return (
    <main className="workspace-page">
      <header className="workspace-header">
        <div className="brand-mark" aria-hidden="true">R</div>
        <div>
          <p className="eyebrow">AI Root Cause Investigation Agent</p>
          <h1>Investigation workspace</h1>
          <p>Trace a KPI movement through tested contributions, evidence, and explicit uncertainty.</p>
        </div>
        <span className="version-badge">V1 · Additive KPI</span>
      </header>

      <div ref={errorRef}><ErrorBanner error={state.apiError} /></div>

      {state.phase === "investigating" ? <LoadingPanel /> : state.phase === "result" && state.result ? (
        <div ref={resultRef} tabIndex="-1"><InvestigationResult result={state.result} onRevise={() => dispatch({ type: "CONFIGURE" })} onNew={handleNew} /></div>
      ) : (
        <InvestigationSetup
          phase={state.phase}
          dataset={state.dataset}
          form={state.form}
          fieldErrors={state.fieldErrors}
          isUploading={state.isUploading}
          isInvestigating={state.isInvestigating}
          onUpload={handleUpload}
          onRemoveDataset={handleRemoveDataset}
          onChange={(field, value) => dispatch({ type: "SET_FIELD", field, value })}
          onToggleDimension={(dimension) => dispatch({ type: "TOGGLE_DIMENSION", dimension })}
          onReview={handleReview}
          onBackToConfigure={() => dispatch({ type: "CONFIGURE" })}
          onRun={handleRun}
        />
      )}
    </main>
  );
}
