
Five edits. Each block below replaces the corresponding section in `README.md`.

---

## 1. Badge (line 13)

**Replace:**
```
[![Playwright](https://img.shields.io/badge/Playwright-19%20passed-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
```

**With:**
```
[![Playwright](https://img.shields.io/badge/Playwright-23%20passed-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
```

---

## 2. Engineering proof — first two table rows (lines 287–288)

**Replace:**
```
| Maintained backend suite | **289 passed · 1 legitimate skip · 0 failed** | Contracts, deterministic calculations, API mapping, lifecycle, failure handling, and regression behavior. |
| Browser release suite | **19 passed · 0 failed** | Public semantics, signed arithmetic, failure recovery, accessibility, responsiveness, themes, and safe export. |
```

**With:**
```
| Maintained backend suite | **323 passed · 1 legitimate skip · 0 failed** | Contracts, deterministic calculations, API mapping, lifecycle, failure handling, and regression behavior. |
| Browser release suite | **23 passed · 0 failed** | Public semantics, signed arithmetic, failure recovery, accessibility, responsiveness, themes, and safe export. |
| Recruiter-demo browser suite | **1 passed · 0 failed** | Public demo path renders end to end without a configured provider. |
```

---

## 3. Testing and validation — results list (lines 450–456)

**Replace:**
```
- backend: **289 passed, 1 skipped, 0 failed**;
- frontend build: **passed**;
- Playwright: **19 passed, 0 failed**;
- controlled benchmark: **5/5 passed**; and
- GitHub Actions backend and frontend gates: **successful**.
```

**With:**
```
- backend: **323 passed, 1 skipped, 0 failed**;
- frontend build: **passed**;
- Playwright release suite: **23 passed, 0 failed**;
- Playwright recruiter-demo suite: **1 passed, 0 failed**;
- controlled benchmark: **5/5 passed**; and
- GitHub Actions backend and frontend gates: **successful**.
```

---

## 4. Product solution — add four capability rows

Append these to the existing capability table, after the `Data-quality abstention` row:

```
| Segment reliability verification | Rejects a leading segment whose own raw data cannot support it: too few backing rows, a category structurally absent from one period, or a fully null baseline. |
| Placeholder-label governance | Detects segment labels that record a data gap rather than a business category (`Not Defined`, `Unknown`, `N/A`). Their movement still counts toward reconciliation, but they cannot carry a descriptive explanation. |
| Numeric role classification | Classifies every numeric column as quantity, identifier, cyclical, or discrete scale during profiling. Only quantities are offered as additive KPIs; a column matching the active time grain is excluded as a dimension. |
| Provider fallback observability | Every degradation to the deterministic path is logged with the `investigation_id`, so a specific investigation can be traced to the path that produced it. |
```

---

## 5. New section — insert after "AI reasoning vs deterministic calculation"

```markdown
## When a correct number is not an answer

The arithmetic in this system was never the hard part. Signed contribution
analysis is deterministic and reconciles exactly. The difficult problem is
knowing when an arithmetically correct result should not be presented as a
business explanation.

Adversarial testing against real datasets surfaced four distinct versions of
that failure. Each is now governed:

| Failure mode | What the system did before | What it does now |
| --- | --- | --- |
| **Thin evidence** | A segment backed by a single row was reported as a strong contributor. | Per-segment row counts are captured before aggregation collapses them. Insufficient sample forces a weakened verdict and a not-ready readiness. |
| **Structural absence** | A category present in the baseline and absent from the comparison was reported as a total decline. | Absence is distinguished from a measured drop. A renamed, discontinued, or pipeline-broken category cannot be certified as the explanation. |
| **Fabricated baseline** | A fully null baseline was silently read as zero, manufacturing a decline that was never measured. | A null baseline is reported as unavailable, not as a movement. |
| **Semantically empty labels** | `Size: Not Defined` — a data-entry gap covering 30% of rows — was selected as the leading contributor and drilled into two levels deeper. | Placeholder labels are detected at profiling time, surfaced in the wizard before the investigation runs, and blocked from carrying a descriptive explanation. Their movement is still counted, so reconciliation still ties out. |

The design rule across all four is the same: **suppress the claim, keep the
arithmetic.** Excluding an untrustworthy segment from the totals would break the
additive tie-out that makes the decomposition auditable. Promoting the
runner-up instead would present a less complete picture as though it were the
whole story. Refusing to certify is the only honest option, and it is what the
system does.

The same principle governs column selection. A numeric column is not
automatically a valid KPI: summing an identifier, an hour-of-day, or a
five-point rating scale is arithmetically valid and analytically meaningless.
Profiling classifies numeric columns by role, and only genuine quantities are
offered as additive KPIs.
```

---

## 6. Honest limitations — append these entries

Add to the end of the existing bullet list:

```
- Verification evaluates the root-level contributor only. On investigations that drill deeper, the verification target no longer matches the conclusion target, and robustness is reported as `not_verified` with an explicit caveat rather than partially applied. The cause is an integration gap: the conclusion resolver walks the investigation path to its deepest node while the verifier reads root-level state that recursion does not update. Two of five challenges are already scope-generic; three hold global values. Honest abstention was chosen over a partial fix that would report one segment's label beside another segment's numbers.
- Placeholder-label detection inherits the same root-level boundary. A semantically empty label is caught when it leads at the top level, not when it wins at depth two or below.
- Numeric columns representing percentages, rates, or ratios are classified as quantities and remain selectable as additive KPIs, though summing them is not meaningful. Cardinality-based detection cannot separate them from genuine quantities; a name-token heuristic was deliberately deferred as lower-confidence. See [Known limitations](docs/KNOWN-LIMITATIONS.md).
- Database failures surface to the client as a single generic registration error. Not exposing internals is intentional; the absence of any operator-facing distinction between schema drift, constraint violation, and connection failure is not.
- Migrations are raw SQL applied manually in numeric order, with no runner or tracking table. This has already caused a real failure in which a committed migration was never applied to the hosted database and every upload failed until it was applied by hand.
```
