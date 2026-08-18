import { titleize } from "@/lib/rcaPresentation";

function FieldError({ id, errors }) {
  const message = errors?.[id];
  return message ? <p className="field-error" id={`${id}-error`}>{message}</p> : null;
}

function describedBy(id, errors, hintId) {
  return [errors?.[id] ? `${id}-error` : null, hintId].filter(Boolean).join(" ") || undefined;
}

function columnsFrom(dataset) {
  return Object.values(dataset?.profile?.columns || {});
}

function isConfidentDate(column) {
  return column.semantic_type === "datetime" && column.date_semantics?.status !== "AMBIGUOUS_DATE_FORMAT";
}

function isIdentifierLike(column, rowCount) {
  const name = String(column.name || "").toLowerCase();
  const ratio = rowCount ? Number(column.unique_count || 0) / rowCount : 0;
  return /(^id$|_id$|^id_|identifier|uuid|_key$)/.test(name) || ratio >= 0.9;
}

function PeriodInput({ prefix, label, grain, value, onChange, errors }) {
  const type = grain === "month" ? "month" : grain === "day" || grain === "week" ? "date" : grain === "year" ? "number" : "text";
  const placeholder = grain === "quarter" ? "2026Q1" : grain === "year" ? "2026" : undefined;
  return (
    <div className="field-group">
      <label htmlFor={prefix}>{label}</label>
      <input
        id={prefix}
        name={prefix}
        type={type}
        value={value}
        min={grain === "year" ? 1 : undefined}
        step={grain === "year" ? 1 : undefined}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={Boolean(errors?.[prefix])}
        aria-describedby={describedBy(prefix, errors, grain === "week" ? "week-period-hint" : undefined)}
      />
      <FieldError id={prefix} errors={errors} />
    </div>
  );
}

function DatasetSummary({ dataset, onReplace, onRemove, disabled, recruiterDemoMode }) {
  const profile = dataset.profile || {};
  const dateColumns = columnsFrom(dataset).filter((column) => column.date_semantics?.min_date);
  return (
    <section className="dataset-summary" aria-labelledby="dataset-summary-title">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Dataset ready</p>
          <h2 id="dataset-summary-title">{dataset.filename}</h2>
        </div>
        <div className="button-row">
          {!recruiterDemoMode && (
            <>
              <label
                className="button secondary compact"
                htmlFor="replace-dataset"
                onDragOver={(event) => { event.preventDefault(); if (!disabled) event.dataTransfer.dropEffect = "copy"; }}
                onDrop={(event) => { event.preventDefault(); if (!disabled && event.dataTransfer.files?.[0]) onReplace(event.dataTransfer.files[0]); }}
              >Replace dataset</label>
              <input
                className="visually-hidden-input"
                id="replace-dataset"
                type="file"
                accept=".csv,.xlsx"
                disabled={disabled}
                onChange={(event) => {
                  const selected = event.target.files?.[0];
                  event.target.value = "";
                  if (selected) onReplace(selected);
                }}
              />
            </>
          )}
          <button className="button ghost compact danger-action" type="button" disabled={disabled} onClick={onRemove}>Remove</button>
        </div>
      </div>
      <dl className="profile-facts">
        <div><dt>Rows</dt><dd>{Number(profile.row_count || 0).toLocaleString()}</dd></div>
        <div><dt>Columns</dt><dd>{profile.column_count ?? 0}</dd></div>
        <div><dt>Duplicates</dt><dd>{profile.duplicate_row_count ?? 0}</dd></div>
        <div><dt>File size</dt><dd>{dataset.size_bytes ? `${(dataset.size_bytes / 1024 / 1024).toFixed(2)} MB` : "Not reported"}</dd></div>
      </dl>
      {dateColumns.length > 0 && (
        <div className="coverage-list">
          {dateColumns.map((column) => (
            <p key={column.name}>
              <strong>{column.name}</strong> coverage: {String(column.date_semantics.min_date).slice(0, 10)} to {String(column.date_semantics.max_date).slice(0, 10)}
              {column.date_semantics.missing_months?.length ? ` · Missing months: ${column.date_semantics.missing_months.join(", ")}` : ""}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

function FileDropZone({ id, disabled, onUpload, children, className = "drop-zone" }) {
  function receive(event) {
    event.preventDefault();
    if (!disabled && event.dataTransfer.files?.[0]) onUpload(event.dataTransfer.files[0]);
  }
  return (
    <label
      className={`${className} ${disabled ? "disabled" : ""}`}
      htmlFor={id}
      onDragOver={(event) => { event.preventDefault(); if (!disabled) event.dataTransfer.dropEffect = "copy"; }}
      onDrop={receive}
    >
      {children}
    </label>
  );
}

function UploadPanel({ onUpload, uploading, errors }) {
  return (
    <section className="setup-card upload-panel" aria-labelledby="upload-title">
      <p className="eyebrow">Step 1 · Evidence</p>
      <h2 id="upload-title">Choose one structured dataset</h2>
      <p className="section-copy">Upload a CSV or Excel file containing the additive KPI, a date field, and the business dimensions you want the agent to test.</p>
      <FileDropZone id="dataset-file" disabled={uploading} onUpload={onUpload}>
        <span className="drop-icon" aria-hidden="true">↑</span>
        <strong>{uploading ? "Uploading and profiling…" : "Choose a CSV or XLSX file"}</strong>
        <span>One dataset only · raw preview rows stay hidden</span>
      </FileDropZone>
      <input
        className="visually-hidden-input"
        id="dataset-file"
        name="dataset-file"
        type="file"
        accept=".csv,.xlsx"
        disabled={uploading}
        aria-describedby={errors?.dataset ? "dataset-error" : undefined}
        onChange={(event) => {
          const selected = event.target.files?.[0];
          event.target.value = "";
          if (selected) onUpload(selected);
        }}
      />
      <FieldError id="dataset" errors={errors} />
    </section>
  );
}

function RecruiterDemoPanel({ onLoadDemo, loading, errors }) {
  return (
    <section className="setup-card upload-panel" aria-labelledby="demo-title">
      <p className="eyebrow">Step 1 · Validated evidence</p>
      <h2 id="demo-title">Run the maintained revenue incident</h2>
      <p className="section-copy">Explore the real governed RCA workflow using the maintained ecommerce benchmark fixture.</p>
      <div className="demo-entry">
        <span className="demo-mark" aria-hidden="true">RCA</span>
        <div>
          <strong>Recruiter-safe demonstration</strong>
          <p>No external data upload is enabled in this public recruiter demo. The server will create a fresh opaque reference to the validated fixture.</p>
        </div>
        <button className="button primary" type="button" onClick={onLoadDemo} disabled={loading}>
          {loading ? "Loading validated demo…" : "Try validated demo"}
        </button>
      </div>
      <FieldError id="dataset" errors={errors} />
    </section>
  );
}

function ConfigurationForm({ dataset, form, errors, onChange, onToggleDimension, onReview }) {
  const columns = columnsFrom(dataset);
  const allNull = new Set(dataset.profile?.all_null_columns || []);
  const constant = new Set(dataset.profile?.constant_columns || []);
  const metricColumns = columns.filter((column) => column.semantic_type === "numeric" && !allNull.has(column.name));
  const timeColumns = columns.filter(isConfidentDate);
  const invalidDates = columns.filter((column) => column.date_semantics && !isConfidentDate(column));
  const eligibleDimensions = columns
    .filter((column) => !allNull.has(column.name) && !constant.has(column.name))
    .filter((column) => ![form.metricColumn, form.timeColumn].includes(column.name))
    .map((column) => ({ ...column, caution: isIdentifierLike(column, dataset.profile?.row_count) }))
    .sort((left, right) => {
      const leftPriority = ["categorical", "boolean"].includes(left.semantic_type) && !left.caution ? 0 : 1;
      const rightPriority = ["categorical", "boolean"].includes(right.semantic_type) && !right.caution ? 0 : 1;
      return leftPriority - rightPriority;
    });
  const selected = new Set(form.dimensions);
  const selectedColumns = eligibleDimensions.filter((column) => selected.has(column.name));

  return (
    <form className="setup-form" onSubmit={(event) => { event.preventDefault(); onReview(); }} noValidate>
      <section className="setup-card" aria-labelledby="kpi-title">
        <p className="eyebrow">Step 2 · KPI definition</p>
        <h2 id="kpi-title">Define the additive KPI</h2>
        <p className="section-copy">The V1 investigation uses a governed SUM. Calculations and thresholds remain server-controlled.</p>
        <div className="form-grid two-columns">
          <div className="field-group">
            <label htmlFor="metricColumn">Metric column</label>
            <select id="metricColumn" value={form.metricColumn} onChange={(event) => onChange("metricColumn", event.target.value)} aria-invalid={Boolean(errors.metricColumn)} aria-describedby={describedBy("metricColumn", errors)}>
              <option value="">Select a numeric field</option>
              {metricColumns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
            </select>
            <FieldError id="metricColumn" errors={errors} />
          </div>
          <div className="field-group">
            <label htmlFor="kpiName">KPI name</label>
            <input id="kpiName" value={form.kpiName} onChange={(event) => onChange("kpiName", event.target.value)} placeholder="Revenue" maxLength={128} aria-invalid={Boolean(errors.kpiName)} aria-describedby={describedBy("kpiName", errors)} />
            <FieldError id="kpiName" errors={errors} />
          </div>
          <div className="field-group">
            <label htmlFor="timeColumn">Time column</label>
            <select id="timeColumn" value={form.timeColumn} onChange={(event) => onChange("timeColumn", event.target.value)} aria-invalid={Boolean(errors.timeColumn)} aria-describedby={describedBy("timeColumn", errors)}>
              <option value="">Select a safely parsed date field</option>
              {timeColumns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
            </select>
            <FieldError id="timeColumn" errors={errors} />
          </div>
          <div className="field-group">
            <label htmlFor="aggregation">Aggregation</label>
            <input id="aggregation" value="SUM · governed additive KPI" readOnly aria-readonly="true" />
          </div>
          <div className="field-group">
            <label htmlFor="grain">Time grain</label>
            <select id="grain" value={form.grain} onChange={(event) => onChange("grain", event.target.value)}>
              <option value="day">Day</option>
              <option value="week">Week</option>
              <option value="month">Month</option>
              <option value="quarter">Quarter</option>
              <option value="year">Year</option>
            </select>
          </div>
          <div className="field-group">
            <label htmlFor="unit">Unit <span className="optional">optional</span></label>
            <input id="unit" value={form.unit} onChange={(event) => onChange("unit", event.target.value)} placeholder="EUR, orders, users" maxLength={32} />
          </div>
        </div>
        {invalidDates.length > 0 && <p className="inline-caution">Not selectable as time fields: {invalidDates.map((column) => column.name).join(", ")}. Their date format was not confidently established.</p>}
        {!metricColumns.length && <p className="inline-blocker">This dataset has no usable numeric KPI column.</p>}
        {!timeColumns.length && <p className="inline-blocker">This dataset has no confidently parsed date column.</p>}
      </section>

      <section className="setup-card" aria-labelledby="period-title">
        <p className="eyebrow">Step 3 · Comparison</p>
        <h2 id="period-title">Choose baseline and comparison periods</h2>
        <p className="section-copy">Use canonical {form.grain} periods. The backend will still verify that both periods are present and analytically safe.</p>
        {form.grain === "week" && <p className="field-hint" id="week-period-hint">Weekly periods use the Monday week-start date.</p>}
        <div className="form-grid two-columns">
          <PeriodInput prefix="baselinePeriod" label="Baseline period" grain={form.grain} value={form.baselinePeriod} onChange={(value) => onChange("baselinePeriod", value)} errors={errors} />
          <PeriodInput prefix="comparisonPeriod" label="Comparison period" grain={form.grain} value={form.comparisonPeriod} onChange={(value) => onChange("comparisonPeriod", value)} errors={errors} />
        </div>
      </section>

      <section className="setup-card" aria-labelledby="dimension-title">
        <p className="eyebrow">Step 4 · Hypotheses</p>
        <h2 id="dimension-title">Approve candidate business dimensions</h2>
        <p className="section-copy">Dimensions are investigation axes. Select 1–12 fields the agent may test; they are not pre-declared causes.</p>
        <fieldset className="dimension-fieldset" aria-describedby={errors.dimensions ? "dimensions-error" : "dimension-selection-hint"}>
          <legend className="sr-only">Candidate business dimensions</legend>
          <p className="field-hint" id="dimension-selection-hint">{form.dimensions.length}/12 selected. Identifier-like and high-cardinality fields require deliberate selection.</p>
          <div className="dimension-list">
            {eligibleDimensions.map((column) => (
              <label key={column.name} className={`dimension-option ${selected.has(column.name) ? "selected" : ""} ${column.caution ? "caution" : ""}`}>
                <input type="checkbox" checked={selected.has(column.name)} disabled={!selected.has(column.name) && form.dimensions.length >= 12} onChange={() => onToggleDimension(column.name)} />
                <span>
                  <strong>{titleize(column.name)}</strong>
                  <small>
                    {column.semantic_type} · {Number(column.unique_count || 0).toLocaleString()} unique · {column.null_pct || 0}% null
                    {Boolean(column.placeholder_pct) && <> · {column.placeholder_pct}% placeholder values</>}
                  </small>
                  {column.caution && <em>High cardinality or identifier-like — select only when analytically meaningful</em>}
                  {Boolean(column.placeholder_pct) && (
                    <em>Contains missing-data placeholders (e.g. &quot;Not Defined&quot;) — these will not support a descriptive explanation even if arithmetically leading</em>
                  )}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <FieldError id="dimensions" errors={errors} />
        {!eligibleDimensions.length && <p className="inline-blocker">No eligible candidate dimensions remain after excluding the KPI, time, all-null, and constant fields.</p>}
        {selectedColumns.some((column) => column.caution) && <p className="inline-caution">Your selection includes a high-cardinality or identifier-like field. Confirm that it represents a meaningful business segment before continuing.</p>}
      </section>

      <div className="sticky-action-row">
        <div><strong>Ready to review?</strong><span>Confirm the bounded investigation contract before it runs.</span></div>
        <button className="button primary" type="submit" disabled={!metricColumns.length || !timeColumns.length || !eligibleDimensions.length}>Review investigation</button>
      </div>
    </form>
  );
}

function ReviewPanel({ dataset, form, onBack, onRun, investigating }) {
  return (
    <section className="setup-card review-panel" aria-labelledby="review-title">
      <p className="eyebrow">Step 5 · Contract review</p>
      <h2 id="review-title">Confirm the bounded investigation</h2>
      <p className="section-copy">The agent will test only this additive KPI, these periods, and these approved dimensions.</p>
      <dl className="review-grid">
        <div><dt>Dataset</dt><dd>{dataset.filename}</dd></div>
        <div><dt>KPI</dt><dd>{form.kpiName} · SUM({form.metricColumn}){form.unit ? ` · ${form.unit}` : ""}</dd></div>
        <div><dt>Time definition</dt><dd>{form.timeColumn} · {titleize(form.grain)}</dd></div>
        <div><dt>Comparison</dt><dd>{form.baselinePeriod} → {form.comparisonPeriod}</dd></div>
        <div className="full"><dt>Approved dimensions</dt><dd>{form.dimensions.map(titleize).join(" · ")}</dd></div>
      </dl>
      <div className="review-boundary">
        <strong>Interpretation boundary</strong>
        <p>The result can identify a leading tested contributor and a stronger descriptive explanation. It does not establish causal proof.</p>
      </div>
      <div className="button-row end">
        <button className="button secondary" type="button" onClick={onBack} disabled={investigating}>Edit definition</button>
        <button className="button primary" type="button" onClick={onRun} disabled={investigating}>{investigating ? "Investigation running…" : "Start investigation"}</button>
      </div>
    </section>
  );
}

export default function InvestigationSetup(props) {
  const { phase, dataset, form, fieldErrors, isUploading, recruiterDemoMode } = props;
  return (
    <div className="setup-shell">
      <nav className="setup-progress" aria-label="Investigation setup progress">
        {["Dataset", "KPI and periods", "Dimensions", "Review"].map((label, index) => {
          const current = !dataset ? 0 : phase === "review" ? 3 : index === 0 ? 0 : 1;
          return <div key={label} className={index < current ? "complete" : index === current ? "current" : ""}><span>{index < current ? "✓" : index + 1}</span><strong>{label}</strong></div>;
        })}
      </nav>
      <div className="setup-content">
        {!dataset ? (
          recruiterDemoMode
            ? <RecruiterDemoPanel onLoadDemo={props.onLoadDemo} loading={isUploading} errors={fieldErrors} />
            : <UploadPanel onUpload={props.onUpload} uploading={isUploading} errors={fieldErrors} />
        ) : (
          <>
            <DatasetSummary dataset={dataset} onReplace={props.onUpload} onRemove={props.onRemoveDataset} disabled={isUploading || props.isInvestigating} recruiterDemoMode={recruiterDemoMode} />
            {phase === "review" ? <ReviewPanel dataset={dataset} form={form} onBack={props.onBackToConfigure} onRun={props.onRun} investigating={props.isInvestigating} /> : <ConfigurationForm dataset={dataset} form={form} errors={fieldErrors} onChange={props.onChange} onToggleDimension={props.onToggleDimension} onReview={props.onReview} />}
          </>
        )}
      </div>
    </div>
  );
}
