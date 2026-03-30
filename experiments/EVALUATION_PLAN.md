# Evaluation Plan — ReactRefactor Agent
**Milestone 3**

---

## Research Questions

**RQ1 — Classifier Accuracy**
> How accurately does the classifier identify which detected smells are genuinely actionable?

**RQ2 — Pipeline Latency and Cost**
> What is the per-task API cost and wall-clock latency, and is the pipeline affordable to run over 2095 smells?

**RQ3 — Pipeline Conservatism**
> At each stage, what fraction of smells are rejected and for what reason? Does the system avoid passing bad refactors to the codebase?

**RQ4 — Refactor Correctness**
> Do accepted refactors correctly resolve the smell without breaking the build, introducing TypeScript errors, or creating new smells?

**RQ5 — Correctness vs. Naive LLM Baseline**
> Does the pipeline produce fewer behavioral breakages than GPT-3.5, GPT-4o, or Codex applied directly to the same smell without tactic constraints or verification?

---

## Empirical Methodology

### Corpus
- **Primary:** `supabase/supabase` — production-grade React/TypeScript codebase. ReactSniffer detected **2095 smells** across 19 smell types (`data/supabase_full/detector/normalized_smells.json`). Chosen because it is large, real-world, and uses modern React patterns (shadcn/ui, react-hook-form, Radix).
- **Secondary:** 6 curated tasks from the Supabase design system (`data/supabase_design_system/`) — used for controlled end-to-end testing and the motivating LLM comparison.

### Setup
- All LLM calls use `temperature=0` for reproducibility
- Model: `gpt-4o-mini` for classify, plan, critique nodes
- Baseline models: `gpt-3.5-turbo` (weak), `gpt-4o` (strong), Codex/GPT-4.1 mini (agent)
- TypeScript gate: `tsc --noEmit` run at project level (not just edited file)
- Build gate: `pnpm build`
- Smell check: ReactSniffer re-run on changed files post-edit

### Sampling for RQ1
50 smells from supabase_full, stratified by smell type frequency. Two team members label each independently (blind); disagreements resolved by discussion. Cohen's kappa reported for inter-rater agreement.

### Sampling for RQ5
Top 6–8 most frequent smell types in supabase_full (by frequency count). 3–4 cases per type → **20–25 total cases**. All four systems receive the identical prompt and code snippet — only the system processing it differs.

### Threats to Validity
- **Internal:** LLM non-determinism mitigated by `temperature=0`. Human labelling subjectivity mitigated by blind labelling, written rubric, and two reviewers.
- **External:** Single repository — results may not generalize to all React codebases.
- **Construct:** TypeScript compilation is necessary but not sufficient for behavioral correctness — a refactor can compile while silently breaking runtime behavior (e.g. React context provider dropped). Human review addresses this gap.

---

## Evaluation Strategies

### E1 — Classifier Precision/Recall *(answers RQ1)*
Run the classifier on the 50 labelled smells. Report precision, recall, F1 per label class, and a confusion matrix. Answerable now — no edit node required.

### E2 — Latency and Cost Instrumentation *(answers RQ2)*
Instrument `runner.py` to log per-task wall time and `response.usage` token counts from each OpenAI call. Run classify + plan on all 2095 smells. Report median latency, P95 latency, cost per 100 tasks (USD), and extrapolated total cost for the full corpus.
```
cost = (input_tokens / 1M × $0.15) + (output_tokens / 1M × $0.60)
```
Answerable now — no edit node required.

### E3 — Multi-Stage Rejection Funnel *(answers RQ3)*
Run the full pipeline on 2095 smells. Report counts at each rejection stage:

```
2095 smells
  ├── Stage 1: Classifier → SKIPPED (non-actionable / needs_review)
  ├── Stage 2: Planner   → SKIPPED (NO_TACTIC)
  ├── Stage 3: Edit      → REJECTED (no-op, no files changed)
  ├── Stage 4: Build/TS  → REJECTED (tsc or pnpm build failed)       [C4]
  ├── Stage 5: Smell     → REJECTED (smell still present / new smell) [C5]
  ├── Stage 6: Critique  → REJECTED (retry limit hit)
  └── ACCEPTED
```

Stages 1–2 answerable now. Stages 3–6 require edit node + C4/C5.

### E4 — Automated Correctness Gates *(answers RQ4)*
On all ACCEPTED outputs, run:
1. `tsc --noEmit` (project-level) — catches type errors and wrong API usage
2. `pnpm build` — catches bundler and runtime module errors
3. ReactSniffer re-run — confirms smell is gone and no new smell introduced
4. Scope containment check — `changed_files ⊆ allowed_edit_scope.allowed_files`

Supplement with human behavioral review on a random sample of 20–30 ACCEPTED cases, evaluating: behavior preserved, all sections present, correct third-party API usage. This catches silent runtime failures that TypeScript cannot (the exact failure class documented in the motivating experiment).

Requires edit node + C4/C5.

### E5 — 4-Way LLM Comparison *(answers RQ5)*
Apply all four systems to the same 20–25 cases using an identical neutral prompt. Evaluate each output on:

| Check | Method |
|---|---|
| Compiles (`tsc --noEmit`) | Automated |
| Build passes | Automated |
| Smell resolved | Automated |
| No new smells | Automated |
| All sections preserved | Human |
| Correct third-party APIs | Human |
| Behavior preserved | Human |

1 case (FormPatternsSidePanel, Large Component) already completed — GPT-3.5 and GPT-4o both dropped the `Form_Shadcn_` context wrapper causing silent validation failure; Codex preserved it but dropped 3 sections. Full 20–25 case results require the edit node.

---

## What Is Answerable at Milestone 3

| | RQ1 | RQ2 | RQ3 | RQ4 | RQ5 |
|---|:---:|:---:|:---:|:---:|:---:|
| Full results now | ✅ | ✅ | Stages 1–2 only | ❌ | 1 case done |
| Requires edit node | — | — | Stages 3–6 | ✅ | ✅ |

**For the presentation:** deliver RQ1 and RQ2 as complete results, present RQ3–RQ5 as methodology with the motivating experiment (RQ5, 1 case) as supporting evidence.
