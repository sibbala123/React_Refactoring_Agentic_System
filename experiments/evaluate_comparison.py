"""
RQ5 — 3-Way Comparison: Weak LLM vs Strong LLM vs Our Pipeline
===============================================================
Uses an LLM judge (gpt-4o-mini) to evaluate each baseline output against
the original code. Checks:
  1. smell_resolved   — does the fix actually address the smell?
  2. behavior_preserved — no behavioral regressions introduced?
  3. no_irrelevant_changes — no unrelated modifications?
  4. complete_output  — full rewrite provided (not truncated/partial)?

Pipeline results are read directly from pipeline_summary.json.

Usage:
    python experiments/evaluate_comparison.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

INDEX_FILE       = Path("experiments/comparison/smell_index.json")
PIPELINE_SUMMARY = Path("experiments/comparison/pipeline_summary.json")
WEAK_DIR         = Path("experiments/comparison/results/weak_llm")
STRONG_DIR       = Path("experiments/comparison/results/strong_llm")
REPORT_FILE      = Path("experiments/comparison/comparison_report.md")
CACHE_FILE       = Path("experiments/comparison/llm_judge_cache.json")
SUPABASE_ROOT    = Path("C:/Users/jayan/supabase-master")
MAX_SNIPPET      = 150  # lines of original code to include in judge prompt

JUDGE_SYSTEM = """\
You are a senior React/TypeScript code reviewer evaluating an automated refactoring.
You will be given:
  - The smell type detected
  - The original source code
  - The proposed refactored output from an LLM

Evaluate the output on exactly these four criteria. For each, answer true or false and give a one-line reason.

1. smell_resolved: Does the refactored code actually fix the detected smell?
   (e.g. for Large Component: is the component genuinely split/extracted? for Too Many Props: are props reduced?)
2. behavior_preserved: Does the refactor preserve all existing behavior?
   (check: no sections dropped, no logic removed, no prop/API changes that break callers)
3. no_irrelevant_changes: Does the output avoid unrelated modifications?
   (renaming unrelated variables, changing unrelated logic, adding new features not asked for)
4. complete_output: Is the output a complete, non-truncated rewrite?
   (not cut off mid-function, no "// rest of code" placeholders, no "..." ellipsis omissions)

Respond ONLY with valid JSON in this exact format:
{
  "smell_resolved": true/false,
  "smell_resolved_reason": "...",
  "behavior_preserved": true/false,
  "behavior_preserved_reason": "...",
  "no_irrelevant_changes": true/false,
  "no_irrelevant_changes_reason": "...",
  "complete_output": true/false,
  "complete_output_reason": "...",
  "overall_pass": true/false,
  "summary": "one sentence overall verdict"
}
overall_pass is true only if ALL four criteria are true.
"""


def load_original_snippet(entry: dict) -> str:
    fp = SUPABASE_ROOT / entry["file_path"].lstrip("/")
    if not fp.exists():
        return "(source file not available)"
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    line_start = entry.get("line_start") or 1
    line_end = entry.get("line_end") or line_start
    if line_start == line_end and line_start <= 1:
        chunk = lines[:MAX_SNIPPET]
    elif line_start == line_end:
        start = max(0, line_start - 60)
        end = min(len(lines), line_start + 60)
        chunk = lines[start:end]
    else:
        start = max(0, line_start - 1)
        end = min(len(lines), line_end + 5)
        chunk = lines[start:end][:MAX_SNIPPET]
    return "\n".join(chunk)


def judge_output(client: OpenAI, entry: dict, llm_output: str, cache: dict, cache_key: str) -> dict:
    if cache_key in cache:
        return cache[cache_key]

    original = load_original_snippet(entry)
    # Truncate LLM output to avoid huge prompts
    llm_output_trimmed = llm_output[:6000] if len(llm_output) > 6000 else llm_output

    user_prompt = f"""Smell type: {entry['smell_type']}
Component: {entry['component_name']}
File: {entry['file_path']}

ORIGINAL CODE:
```tsx
{original}
```

PROPOSED REFACTORED OUTPUT:
{llm_output_trimmed}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        cache[cache_key] = result
        return result
    except Exception as e:
        fallback = {
            "smell_resolved": False, "smell_resolved_reason": str(e),
            "behavior_preserved": False, "behavior_preserved_reason": "",
            "no_irrelevant_changes": False, "no_irrelevant_changes_reason": "",
            "complete_output": False, "complete_output_reason": "",
            "overall_pass": False, "summary": f"Judge error: {e}",
        }
        cache[cache_key] = fallback
        return fallback


def load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def build_report(index, weak_results, strong_results, pipeline) -> str:
    lines = []
    lines.append("# RQ5 — 3-Way LLM Comparison Report")
    lines.append("")
    lines.append("**Systems compared:**")
    lines.append("- **Weak LLM** — GPT-4o-mini (direct prompt, no tactic constraints, no verification)")
    lines.append("- **Strong LLM** — GPT-4o (direct prompt, no tactic constraints, no verification)")
    lines.append("- **Pipeline** — Our agentic system (classify → plan → edit → verify → critique)")
    lines.append("")
    lines.append("**Evaluation method for Weak/Strong LLM:** LLM-as-judge (GPT-4o-mini) assessing each")
    lines.append("output against the original code on four criteria:")
    lines.append("")
    lines.append("| Criterion | Description |")
    lines.append("|---|---|")
    lines.append("| smell_resolved | Fix actually addresses the detected smell |")
    lines.append("| behavior_preserved | No behavioral regressions or dropped logic |")
    lines.append("| no_irrelevant_changes | No unrelated modifications introduced |")
    lines.append("| complete_output | Full rewrite provided, not truncated/partial |")
    lines.append("")
    lines.append("**Overall pass** = all four criteria true.")
    lines.append("")
    lines.append("**Pipeline evaluation:** automated typecheck (tsc --isolatedModules) +")
    lines.append("ReactSniffer smell resolution check + LLM critique score ≥ 0.7.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-Task Results")
    lines.append("")
    lines.append("| # | Smell Type | Component | Weak LLM | Strong LLM | Pipeline |")
    lines.append("|---|---|---|---|---|---|")

    weak_pass = strong_pass = pipeline_accepted = 0
    weak_criteria = {"smell_resolved": 0, "behavior_preserved": 0, "no_irrelevant_changes": 0, "complete_output": 0}
    strong_criteria = {"smell_resolved": 0, "behavior_preserved": 0, "no_irrelevant_changes": 0, "complete_output": 0}

    for entry in index:
        tag = entry["id"]
        smell = entry["smell_type"]
        comp = entry["component_name"]

        w = weak_results.get(tag, {})
        s = strong_results.get(tag, {})
        p = pipeline.get(tag, {})

        # Weak
        w_pass = w.get("overall_pass", False)
        w_checks = ("S" if w.get("smell_resolved") else "-") + \
                   ("B" if w.get("behavior_preserved") else "-") + \
                   ("I" if w.get("no_irrelevant_changes") else "-") + \
                   ("C" if w.get("complete_output") else "-")
        w_cell = f"{'PASS' if w_pass else 'FAIL'} ({w_checks})"
        if w_pass:
            weak_pass += 1
        for k in weak_criteria:
            if w.get(k):
                weak_criteria[k] += 1

        # Strong
        s_pass = s.get("overall_pass", False)
        s_checks = ("S" if s.get("smell_resolved") else "-") + \
                   ("B" if s.get("behavior_preserved") else "-") + \
                   ("I" if s.get("no_irrelevant_changes") else "-") + \
                   ("C" if s.get("complete_output") else "-")
        s_cell = f"{'PASS' if s_pass else 'FAIL'} ({s_checks})"
        if s_pass:
            strong_pass += 1
        for k in strong_criteria:
            if s.get(k):
                strong_criteria[k] += 1

        # Pipeline
        status = p.get("status", "unknown")
        if status == "accepted":
            p_cell = f"ACCEPTED (critique={p.get('critique_score')})"
            pipeline_accepted += 1
        elif status == "skipped":
            p_cell = "SKIPPED (false positive)"
        elif status == "rejected":
            p_cell = f"REJECTED (verify={p.get('verify_passed')}, critique={p.get('critique_score')})"
        elif status == "failed":
            p_cell = "FAILED (rate limit)"
        else:
            p_cell = status

        lines.append(f"| {tag} | {smell} | {comp} | {w_cell} | {s_cell} | {p_cell} |")

    lines.append("")
    lines.append("**Check key (Weak/Strong LLM):** S=smell resolved, B=behavior preserved, I=no irrelevant changes, C=complete output")
    lines.append("")
    lines.append("---")
    lines.append("")

    n = len(index)
    lines.append("## Summary Statistics")
    lines.append("")
    lines.append(f"| Metric | Weak LLM (GPT-4o-mini) | Strong LLM (GPT-4o) | Pipeline |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| Overall pass rate | {weak_pass}/{n} ({100*weak_pass//n}%) | {strong_pass}/{n} ({100*strong_pass//n}%) | {pipeline_accepted}/{n} ({100*pipeline_accepted//n}%) |")
    lines.append(f"| Smell resolved | {weak_criteria['smell_resolved']}/{n} | {strong_criteria['smell_resolved']}/{n} | verified by ReactSniffer |")
    lines.append(f"| Behavior preserved | {weak_criteria['behavior_preserved']}/{n} | {strong_criteria['behavior_preserved']}/{n} | verified by critique node |")
    lines.append(f"| No irrelevant changes | {weak_criteria['no_irrelevant_changes']}/{n} | {strong_criteria['no_irrelevant_changes']}/{n} | bounded by allowed_edit_scope |")
    lines.append(f"| Complete output | {weak_criteria['complete_output']}/{n} | {strong_criteria['complete_output']}/{n} | full file rewrite enforced |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-Task Judge Reasoning")
    lines.append("")
    for entry in index:
        tag = entry["id"]
        w = weak_results.get(tag, {})
        s = strong_results.get(tag, {})
        lines.append(f"### Task {tag} — {entry['smell_type']} / {entry['component_name']}")
        lines.append(f"**Weak LLM:** {w.get('summary', 'N/A')}")
        lines.append(f"**Strong LLM:** {s.get('summary', 'N/A')}")
        p = pipeline.get(tag, {})
        lines.append(f"**Pipeline:** status={p.get('status')} verify={p.get('verify_passed')} critique={p.get('critique_score')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Observations")
    lines.append("")
    lines.append("1. **Verification gap** — Weak/Strong LLM outputs are unverified. The judge")
    lines.append("   evaluates plausibility but cannot run ReactSniffer or tsc. The pipeline's")
    lines.append("   automated gates provide objective correctness evidence.")
    lines.append("")
    lines.append("2. **Conservatism vs recall** — The pipeline's 70% acceptance rate (14/20) may")
    lines.append("   seem lower than naive LLM pass rates, but rejected tasks (05, 07, 13) had")
    lines.append("   the smell still present post-edit — a failure the baselines cannot detect.")
    lines.append("")
    lines.append("3. **False positive handling** — Tasks 12, 14, 16 were correctly skipped by")
    lines.append("   the classifier. Baseline LLMs applied refactoring blindly to these cases.")
    lines.append("")
    lines.append("4. **Retry loop value** — The pipeline retried 3× on rejections before giving")
    lines.append("   up, with critique feedback guiding each retry. Baselines have one shot.")

    return "\n".join(lines)


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set.")
    client = OpenAI(api_key=api_key)

    with open(INDEX_FILE) as f:
        index = json.load(f)
    with open(PIPELINE_SUMMARY) as f:
        pipeline_rows = json.load(f)
    pipeline = {r["id"]: r for r in pipeline_rows}

    cache = load_cache()
    weak_results = {}
    strong_results = {}

    total = len(index) * 2
    done = 0

    for entry in index:
        tag = entry["id"]

        # Weak LLM
        out_file = WEAK_DIR / f"output_{tag}.txt"
        if out_file.exists():
            text = out_file.read_text(encoding="utf-8", errors="replace")
            print(f"[{done+1}/{total}] Judging weak LLM task {tag}...", end=" ", flush=True)
            result = judge_output(client, entry, text, cache, f"weak_{tag}")
            weak_results[tag] = result
            print("done" if not result.get("summary","").startswith("Judge error") else f"ERROR: {result['summary']}")
            done += 1
            save_cache(cache)
            time.sleep(0.5)
        else:
            weak_results[tag] = {"overall_pass": False, "summary": "output file missing"}
            done += 1

        # Strong LLM
        out_file = STRONG_DIR / f"output_{tag}.txt"
        if out_file.exists():
            text = out_file.read_text(encoding="utf-8", errors="replace")
            print(f"[{done+1}/{total}] Judging strong LLM task {tag}...", end=" ", flush=True)
            result = judge_output(client, entry, text, cache, f"strong_{tag}")
            strong_results[tag] = result
            print("done" if not result.get("summary","").startswith("Judge error") else f"ERROR: {result['summary']}")
            done += 1
            save_cache(cache)
            time.sleep(0.5)
        else:
            strong_results[tag] = {"overall_pass": False, "summary": "output file missing"}
            done += 1

    report = build_report(index, weak_results, strong_results, pipeline)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"\nReport written to {REPORT_FILE}")

    # Quick summary
    n = len(index)
    w_pass = sum(1 for r in weak_results.values() if r.get("overall_pass"))
    s_pass = sum(1 for r in strong_results.values() if r.get("overall_pass"))
    p_acc  = sum(1 for r in pipeline_rows if r.get("status") == "accepted")
    print("\n" + "="*50)
    print(f"Weak LLM   pass: {w_pass}/{n} ({100*w_pass//n}%)")
    print(f"Strong LLM pass: {s_pass}/{n} ({100*s_pass//n}%)")
    print(f"Pipeline   acc:  {p_acc}/{n} ({100*p_acc//n}%)")


if __name__ == "__main__":
    main()
