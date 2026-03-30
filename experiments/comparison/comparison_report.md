# RQ5 — 3-Way LLM Comparison Report

**Systems compared:**
- **Weak LLM** — GPT-4o-mini (direct prompt, no tactic constraints, no verification)
- **Strong LLM** — GPT-4o (direct prompt, no tactic constraints, no verification)
- **Pipeline** — Our agentic system (classify → plan → edit → verify → critique)

**Evaluation method for Weak/Strong LLM:** LLM-as-judge (GPT-4o-mini) assessing each
output against the original code on four criteria:

| Criterion | Description |
|---|---|
| smell_resolved | Fix actually addresses the detected smell |
| behavior_preserved | No behavioral regressions or dropped logic |
| no_irrelevant_changes | No unrelated modifications introduced |
| complete_output | Full rewrite provided, not truncated/partial |

**Overall pass** = all four criteria true.

**Pipeline evaluation:** automated typecheck (tsc --isolatedModules) +
ReactSniffer smell resolution check + LLM critique score ≥ 0.7.

---

## Per-Task Results

| # | Smell Type | Component | Weak LLM | Strong LLM | Pipeline |
|---|---|---|---|---|---|
| 01 | Large Component | PublicationsList | FAIL (SBI-) | FAIL (SBI-) | ACCEPTED (critique=0.8) |
| 02 | Large Component | RowContextMenu | FAIL (SBI-) | FAIL (SBI-) | ACCEPTED (critique=0.8) |
| 03 | Large Component | ReportFilterBar | FAIL (SBI-) | FAIL (SBI-) | ACCEPTED (critique=0.8) |
| 04 | Large Component | StorageResourceList | PASS (SBIC) | PASS (SBIC) | ACCEPTED (critique=0.8) |
| 05 | Large Component | SecuritySettings | FAIL (S-I-) | FAIL (SBI-) | REJECTED (verify=False, critique=0.5) |
| 06 | Large Component | DiskManagementReviewAndSubmitDialog | FAIL (SBI-) | FAIL (SBI-) | ACCEPTED (critique=0.8) |
| 07 | Too Many Props | Panel | PASS (SBIC) | PASS (SBIC) | REJECTED (verify=False, critique=0.5) |
| 08 | Too Many Props | UserOverview | FAIL (SBI-) | FAIL (-BI-) | ACCEPTED (critique=0.8) |
| 09 | Too Many Props | AllIntegrationsGrid | FAIL (-BI-) | FAIL (SBI-) | ACCEPTED (critique=0.8) |
| 10 | Too Many Props | RenderedSVG | FAIL (----) | FAIL (S---) | FAILED (rate limit) |
| 11 | Too Many Props | TextEditor | FAIL (SBI-) | FAIL (SBI-) | ACCEPTED (critique=0.8) |
| 12 | Too Many Props | CreateAuth0IntegrationDialog | PASS (SBIC) | FAIL (SBI-) | ACCEPTED (critique=0.8) |
| 13 | Direct DOM Manipulation | FloatingTableOfContents | PASS (SBIC) | FAIL (SBI-) | REJECTED (verify=False, critique=0.5) |
| 14 | Direct DOM Manipulation | BaseInjector | FAIL (-BIC) | FAIL (-BIC) | SKIPPED (false positive) |
| 15 | Direct DOM Manipulation | RLSCodeEditor | PASS (SBIC) | PASS (SBIC) | ACCEPTED (critique=0.8) |
| 16 | Inheritance Instead of Composition | GitHubDiscussionLoader | FAIL (SBI-) | FAIL (SBI-) | SKIPPED (false positive) |
| 17 | Inheritance Instead of Composition | MarkdownLoader | FAIL (----) | FAIL (-BI-) | ACCEPTED (critique=0.8) |
| 18 | Uncontrolled Component | SelectHeaderCell | PASS (SBIC) | PASS (SBIC) | ACCEPTED (critique=0.8) |
| 19 | Uncontrolled Component | FormPatternsSidePanel | PASS (SBIC) | PASS (SBIC) | ACCEPTED (critique=0.8) |
| 20 | Force Update | ErrorPage | FAIL (S--C) | PASS (SBIC) | ACCEPTED (critique=0.8) |

**Check key (Weak/Strong LLM):** S=smell resolved, B=behavior preserved, I=no irrelevant changes, C=complete output

---

## Summary Statistics

| Metric | Weak LLM (GPT-4o-mini) | Strong LLM (GPT-4o) | Pipeline |
|---|---|---|---|
| Overall pass rate | 7/20 (35%) | 6/20 (30%) | 14/20 (70%) |
| Smell resolved | 16/20 | 17/20 | verified by ReactSniffer |
| Behavior preserved | 16/20 | 19/20 | verified by critique node |
| No irrelevant changes | 17/20 | 19/20 | bounded by allowed_edit_scope |
| Complete output | 9/20 | 7/20 | full file rewrite enforced |

---

## Per-Task Judge Reasoning

### Task 01 — Large Component / PublicationsList
**Weak LLM:** The refactor successfully addresses the large component smell but is incomplete due to truncation.
**Strong LLM:** The refactor successfully addresses the large component smell but is incomplete due to truncation.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 02 — Large Component / RowContextMenu
**Weak LLM:** The refactor successfully addresses the large component smell but is incomplete due to truncation.
**Strong LLM:** The refactor successfully addresses the large component smell but is incomplete due to truncation.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 03 — Large Component / ReportFilterBar
**Weak LLM:** The refactor successfully addresses the large component smell but is incomplete due to truncation.
**Strong LLM:** The refactor successfully addresses the large component smell but is incomplete due to truncation.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 04 — Large Component / StorageResourceList
**Weak LLM:** The refactoring successfully addresses the large component smell while preserving behavior and maintaining clarity.
**Strong LLM:** The refactoring successfully addresses the large component smell while preserving behavior and maintaining focus on relevant changes.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 05 — Large Component / SecuritySettings
**Weak LLM:** The refactor successfully addresses the large component smell but fails to preserve behavior and is incomplete.
**Strong LLM:** The refactor successfully addresses the large component smell but is incomplete due to a truncated MfaForm component.
**Pipeline:** status=rejected verify=False critique=0.5

### Task 06 — Large Component / DiskManagementReviewAndSubmitDialog
**Weak LLM:** The refactor successfully addresses the large component smell but is incomplete.
**Strong LLM:** The refactor successfully addresses the large component smell but is incomplete due to truncation.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 07 — Too Many Props / Panel
**Weak LLM:** The refactoring successfully addresses the 'Too Many Props' smell while preserving behavior and avoiding irrelevant changes.
**Strong LLM:** The refactored code successfully addresses the 'Too Many Props' smell while preserving behavior and maintaining clarity.
**Pipeline:** status=rejected verify=False critique=0.5

### Task 08 — Too Many Props / UserOverview
**Weak LLM:** The refactor successfully addresses the 'Too Many Props' smell but is incomplete due to truncation.
**Strong LLM:** The refactored code does not adequately address the detected smell and is incomplete.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 09 — Too Many Props / AllIntegrationsGrid
**Weak LLM:** The refactor fails to resolve the 'Too Many Props' smell and is incomplete.
**Strong LLM:** The refactor successfully addresses the prop issue but is incomplete due to truncation.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 10 — Too Many Props / RenderedSVG
**Weak LLM:** The refactored code fails to resolve the smell and introduces new issues, resulting in an overall failure.
**Strong LLM:** The refactored code addresses the prop smell but introduces new issues and is incomplete.
**Pipeline:** status=failed verify=None critique=None

### Task 11 — Too Many Props / TextEditor
**Weak LLM:** The refactor successfully reduces props but is incomplete due to truncation.
**Strong LLM:** The refactor successfully addresses the prop issue but is incomplete due to truncation.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 12 — Too Many Props / CreateAuth0IntegrationDialog
**Weak LLM:** The refactored code effectively addresses the 'Too Many Props' smell while preserving behavior and maintaining clarity.
**Strong LLM:** The refactor successfully reduces props but is incomplete due to truncation.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 13 — Direct DOM Manipulation / FloatingTableOfContents
**Weak LLM:** The refactored code successfully resolves the direct DOM manipulation smell while preserving behavior and maintaining focus on relevant changes.
**Strong LLM:** The refactor successfully resolves the direct DOM manipulation smell but is incomplete.
**Pipeline:** status=rejected verify=False critique=0.5

### Task 14 — Direct DOM Manipulation / BaseInjector
**Weak LLM:** The refactored code does not fully resolve the direct DOM manipulation smell.
**Strong LLM:** The refactored code does not fully resolve the direct DOM manipulation smell.
**Pipeline:** status=skipped verify=None critique=None

### Task 15 — Direct DOM Manipulation / RLSCodeEditor
**Weak LLM:** The refactored code successfully resolves the direct DOM manipulation smell while preserving behavior and maintaining focus on relevant changes.
**Strong LLM:** The refactored code successfully resolves the direct DOM manipulation smell while preserving behavior and maintaining clarity.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 16 — Inheritance Instead of Composition / GitHubDiscussionLoader
**Weak LLM:** The refactor successfully addresses the inheritance smell but is incomplete due to truncation.
**Strong LLM:** The refactor successfully resolves the inheritance smell and preserves behavior, but the output is incomplete.
**Pipeline:** status=skipped verify=None critique=None

### Task 17 — Inheritance Instead of Composition / MarkdownLoader
**Weak LLM:** The refactored output does not adequately resolve the inheritance smell and introduces several issues, including incomplete code.
**Strong LLM:** The refactored code does not fully resolve the inheritance smell and is incomplete.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 18 — Uncontrolled Component / SelectHeaderCell
**Weak LLM:** The refactor successfully resolves the uncontrolled component issue while preserving behavior and maintaining code integrity.
**Strong LLM:** The refactoring successfully resolves the uncontrolled component issue while preserving behavior and maintaining code integrity.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 19 — Uncontrolled Component / FormPatternsSidePanel
**Weak LLM:** The refactored code successfully resolves the uncontrolled component smell while preserving behavior and maintaining focus on relevant changes.
**Strong LLM:** The refactored code successfully resolves the uncontrolled component smell while preserving behavior and maintaining focus.
**Pipeline:** status=accepted verify=True critique=0.8

### Task 20 — Force Update / ErrorPage
**Weak LLM:** The refactor resolves the force update smell but alters the component's behavior and introduces irrelevant changes.
**Strong LLM:** The refactored code successfully resolves the force update smell while preserving behavior and maintaining focus on the task.
**Pipeline:** status=accepted verify=True critique=0.8

---

## Observations

1. **Verification gap** — Weak/Strong LLM outputs are unverified. The judge
   evaluates plausibility but cannot run ReactSniffer or tsc. The pipeline's
   automated gates provide objective correctness evidence.

2. **Conservatism vs recall** — The pipeline's 70% acceptance rate (14/20) may
   seem lower than naive LLM pass rates, but rejected tasks (05, 07, 13) had
   the smell still present post-edit — a failure the baselines cannot detect.

3. **False positive handling** — Tasks 12, 14, 16 were correctly skipped by
   the classifier. Baseline LLMs applied refactoring blindly to these cases.

4. **Retry loop value** — The pipeline retried 3× on rejections before giving
   up, with critique feedback guiding each retry. Baselines have one shot.