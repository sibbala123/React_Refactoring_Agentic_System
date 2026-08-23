# Curated Examples — Validation Against Real Developer Commits

These 5 examples are hand-picked from a larger run (474 tasks, 6 real production
repositories, see `experiments/results/` and `experiments/EXPERIMENT_NOTES.md`) that tested
the LangGraph refactoring pipeline against real historical GitHub commits: for each commit
where a human developer fixed a React code smell, the pipeline was run on the code *just
before* that fix, with no visibility into what the real developer did.

Each folder contains:
- `before.*` — the file exactly as it was before any edit (matches the GitHub blob at the parent commit)
- `after.*` — what the pipeline produced
- `pipeline.diff` — unified diff of the pipeline's edit
- `developer.diff` — the real developer's own diff for the same file, for reference
- `task_summary.json` — the pipeline's full decision trail (classifier verdict, chosen tactic, retry count, critique score, verification checks)

Three of these show the pipeline working correctly. Two show a real bug it had — found by
manually reading the diffs against the real commits below rather than trusting the
pipeline's own pass/fail verdict, and since fixed (see the `usage_safety` check added to
`langgraph_pipeline/nodes/verify.py`).

---

## 1. `01_prometheus_Status_LargeComponent` — independently converged with the real fix

**Smell:** Large Component · **Tactic:** `extract_component` · **Critique score:** 0.9

- File before: https://github.com/prometheus/prometheus/blob/a85e7aac0e4b32bcc6fabbb6f4059842124bc05a/web/ui/react-app/src/pages/Status.tsx
- Developer's commit: https://github.com/prometheus/prometheus/commit/8a9509b0a85430532ee9a01a9f8086ca916275bc

The pipeline extracted the duplicated `<tr><th>/<td>` table-row JSX into its own `StatusRow`
component — the exact same structural extraction the real Prometheus developer made in their
own, larger accompanying refactor. Independent agreement with a human engineer, without ever
seeing their commit.

## 2. `02_rocketchat_UsageSection_DuplicatedCode` — clean duplication extraction

**Smell:** Duplicated Code · **Tactic:** `extract_duplicated_jsx_to_component` · **Critique score:** 0.9

- File before: https://github.com/RocketChat/Rocket.Chat/blob/50c69e22f6ddeb0e8066c93f41ffeaf82028fe60/client/components/admin/info/UsageSection.js
- Developer's commit: https://github.com/RocketChat/Rocket.Chat/commit/c8a36350ac7718b303f24fe19663e155756030dc

27 near-identical `<DescriptionList.Entry label=...>{...}</DescriptionList.Entry>` lines
collapsed into one small `DescriptionEntry` helper component, called 27 times with explicit
props. Nothing dropped, behaviorally identical.

## 3. `03_rocketchat_RegisterServerStep_TooManyProps` — clean split_component

**Smell:** Too Many Props · **Tactic:** `split_component` · **Critique score:** 0.8

- File before: https://github.com/RocketChat/Rocket.Chat/blob/50c69e22f6ddeb0e8066c93f41ffeaf82028fe60/client/components/setupWizard/steps/RegisterServerStep.js
- Developer's commit: https://github.com/RocketChat/Rocket.Chat/commit/c8a36350ac7718b303f24fe19663e155756030dc

Extracted the render body into a `RegistrationOptions` sub-component with every value
threaded through as an explicit prop.

## 4. `04_grafana_Ticks_DeadCode_BUG_FOUND` — the bug that motivated the fix

**Smell:** Dead Code · **Tactic:** `remove_unused_props` · **Critique score:** 0.8 (passed everything — wrongly)

- File before: https://github.com/grafana/grafana/blob/754dfdfa875dbb78cf560076805c29948092c0ab/packages/jaeger-ui-components/src/TraceTimelineViewer/Ticks.tsx
- Developer's commit: https://github.com/grafana/grafana/commit/cf1ebd5a3df752ea9a2b2bb1f9a191c9d9ee6696

The pipeline removed the `startTime`/`endTime` props as "unused," but left the duration
calculation that depended on them in place — now hardcoded to `0`, with a comment it wrote
itself admitting *"endTime and startTime are removed, so viewingDuration is always 0."* The
tick-label feature is silently, permanently broken. `tsc`, the ReactSniffer re-scan, and
critique all passed this — none of them check whether a removed identifier was still in use.
This is the case that led to the `usage_safety` verification gate.

## 5. `05_superset_SaveModal_DeadCode_BUG_FOUND` — the same bug, a second time

**Smell:** Dead Code · **Tactic:** `remove_unused_props` · **Critique score:** 0.8 (also wrongly passed)

- File before: https://github.com/apache/superset/blob/89f5785666c225de2ef271e1ff8759e3af36ab7b/superset-frontend/src/dashboard/components/SaveModal.tsx
- Developer's commit: https://github.com/apache/superset/commit/4bb29b6f04c2c23585805bbac7349f2d2c9876bb

Removed `colorScheme`/`colorNamespace` props but left `CategoricalColorNamespace.getScale(colorScheme, colorNamespace)` — now called with no arguments — and hardcoded `labelColors` to `{}`. Dashboard label coloring silently breaks on save.

---

**Takeaway:** across every manually-reviewed example, extraction-family tactics
(`extract_component`, `split_component`, `extract_duplicated_*`) were reliable; removal-family
tactics (`remove_unused_props`, `remove_unused_state`, `remove_props_in_initial_state`) were
not, until the `usage_safety` check was added. See `agentic_refactor_system/langgraph_pipeline/nodes/verify.py`
for the fix and `experiments/results/summary.csv` for the full 474-task run this was drawn from.
