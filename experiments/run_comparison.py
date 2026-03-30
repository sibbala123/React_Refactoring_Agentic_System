"""
RQ5 — 4-Way LLM Comparison Experiment
======================================
Selects 20 diverse code smells from supabase_full, generates a neutral prompt
for each, and runs GPT-4o-mini (weak) and GPT-4o (strong) automatically.

Codex outputs are collected manually:
  1. Run this script — it writes experiments/comparison/prompts/prompt_XX.txt
  2. Paste each prompt into VS Code Codex, save output to
     experiments/comparison/results/codex/output_XX.txt
  3. Run evaluate_comparison.py to score all four systems.

Our pipeline results are generated separately via test_pipeline.py.

Usage:
    python experiments/run_comparison.py
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from collections import defaultdict

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

SUPABASE_ROOT = Path("C:/Users/jayan/supabase-master")
SMELLS_FILE   = Path("data/supabase_full/detector/normalized_smells.json")
OUT_DIR       = Path("experiments/comparison")
RANDOM_SEED   = 42

# How many cases to pick per smell type
TARGETS = {
    "Large Component":               6,
    "Too Many Props":                6,
    "Direct DOM Manipulation":       3,
    "Inheritance Instead of Composition": 2,
    "Uncontrolled Component":        2,
    "Force Update":                  1,
}

# Max lines of code to include in the prompt snippet
MAX_SNIPPET_LINES = 200

# ── Prompt template (identical for all three baseline systems) ─────────────────

PROMPT_TEMPLATE = """\
You are a senior React/TypeScript engineer.

A static analysis tool detected the following code smell in this file:

Smell type : {smell_type}
File       : {file_path}
Component  : {component_name}
Lines      : {line_start}–{line_end}

```tsx
{snippet}
```

Refactor the component to resolve this code smell while preserving all existing behavior.
Provide the complete refactored code for every file you modify.
Do not truncate or summarise — output the full rewritten content.
"""

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_smells() -> list[dict]:
    with open(SMELLS_FILE) as f:
        return json.load(f)["smells"]


def extract_snippet(file_path: str, line_start: int, line_end: int) -> str:
    """Read the relevant lines from the local Supabase source."""
    abs_path = SUPABASE_ROOT / file_path.lstrip("/")
    if not abs_path.exists():
        return "(source file not available)"
    lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()

    # Smell at a single line or line 1 → use whole file up to MAX_SNIPPET_LINES
    if line_start == line_end:
        if line_start <= 1:
            chunk = lines[:MAX_SNIPPET_LINES]
        else:
            # Expand ±80 lines around the single smell line
            start = max(0, line_start - 80)
            end   = min(len(lines), line_start + 80)
            chunk = lines[start:end]
    else:
        start = max(0, line_start - 1)
        end   = min(len(lines), line_end + 10)
        chunk = lines[start:end]
        if len(chunk) > MAX_SNIPPET_LINES:
            chunk = chunk[:MAX_SNIPPET_LINES]

    return "\n".join(chunk)


def select_smells() -> list[dict]:
    """Stratified random sample — one unique file per entry."""
    random.seed(RANDOM_SEED)
    all_smells = load_smells()

    by_type: dict[str, list[dict]] = defaultdict(list)
    seen_keys: set[tuple] = set()

    for s in all_smells:
        t = s.get("smell_type", "")
        fp = s.get("file_path", "")
        # Deduplicate by (smell_type, file_path, line_start) — same location same type
        key = (t, fp, s.get("line_start", 0))
        if t not in TARGETS:
            continue
        if key in seen_keys:
            continue
        abs_path = SUPABASE_ROOT / fp.lstrip("/")
        if abs_path.exists():
            seen_keys.add(key)
            by_type[t].append(s)

    selected: list[dict] = []
    for smell_type, count in TARGETS.items():
        pool = by_type[smell_type]
        picked = random.sample(pool, min(count, len(pool)))
        selected.extend(picked)

    return selected


def build_prompt(smell: dict) -> str:
    snippet = extract_snippet(
        smell["file_path"],
        smell.get("line_start", 1),
        smell.get("line_end", 1),
    )
    return PROMPT_TEMPLATE.format(
        smell_type     = smell["smell_type"],
        file_path      = smell["file_path"],
        component_name = smell.get("component_name", "unknown"),
        line_start     = smell.get("line_start", "?"),
        line_end       = smell.get("line_end", "?"),
        snippet        = snippet,
    )


def call_llm(client: OpenAI, model: str, prompt: str) -> tuple[str, dict]:
    """Call OpenAI and return (response_text, usage_dict)."""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    text  = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens":     response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens":      response.usage.total_tokens,
    }
    return text, usage


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set.")
    client = OpenAI(api_key=api_key)

    # Create output directories
    prompts_dir    = OUT_DIR / "prompts"
    weak_dir       = OUT_DIR / "results" / "weak_llm"
    strong_dir     = OUT_DIR / "results" / "strong_llm"
    codex_dir      = OUT_DIR / "results" / "codex"
    pipeline_dir   = OUT_DIR / "results" / "pipeline"
    for d in [prompts_dir, weak_dir, strong_dir, codex_dir, pipeline_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Select smells
    smells = select_smells()
    print(f"\nSelected {len(smells)} smells:")
    for i, s in enumerate(smells, 1):
        print(f"  {i:02d}. [{s['smell_type']}] {s['file_path'][-55:]}")

    # Save smell index
    index = []
    for i, s in enumerate(smells, 1):
        index.append({
            "id":             f"{i:02d}",
            "smell_type":     s["smell_type"],
            "file_path":      s["file_path"],
            "component_name": s.get("component_name", "unknown"),
            "line_start":     s.get("line_start"),
            "line_end":       s.get("line_end"),
            "smell_id":       s.get("smell_id"),
        })
    with open(OUT_DIR / "smell_index.json", "w") as f:
        json.dump(index, f, indent=2)

    total_weak_tokens   = 0
    total_strong_tokens = 0
    combined_lines: list[str] = [
        "CODEX PROMPTS — 20 Code Smell Refactoring Tasks",
        "Paste each prompt into VS Code Codex one at a time.",
        "Save each output to experiments/comparison/results/codex/output_XX.txt",
        "=" * 60 + "\n",
    ]

    print("\n" + "=" * 60)
    print("Running gpt-4o-mini and gpt-4o on all 20 smells...")
    print("=" * 60)

    for i, smell in enumerate(smells, 1):
        tag    = f"{i:02d}"
        prompt = build_prompt(smell)

        # Save prompt file for Codex (manual paste)
        prompt_file = prompts_dir / f"prompt_{tag}.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        # Create empty Codex placeholder if not already filled
        codex_out = codex_dir / f"output_{tag}.txt"
        if not codex_out.exists():
            codex_out.write_text(
                f"# Paste Codex output here for smell {tag}\n"
                f"# Smell type : {smell['smell_type']}\n"
                f"# File       : {smell['file_path']}\n",
                encoding="utf-8",
            )

        # Append to combined codex prompts file
        combined_lines.append(f"{'='*60}")
        combined_lines.append(f"PROMPT {tag}/20 — {smell['smell_type']}")
        combined_lines.append(f"Component : {smell.get('component_name', 'unknown')}")
        combined_lines.append(f"File      : {smell['file_path']}")
        combined_lines.append(f"{'='*60}")
        combined_lines.append(prompt)
        combined_lines.append(f"\n{'─'*60}\n")

        print(f"\n[{tag}/20] {smell['smell_type']} — {smell['file_path'][-50:]}")

        # GPT-4o-mini (weak)
        print(f"  gpt-4o-mini ...", end=" ", flush=True)
        weak_text, weak_usage = call_llm(client, "gpt-4o-mini", prompt)
        (weak_dir / f"output_{tag}.txt").write_text(weak_text, encoding="utf-8")
        (weak_dir / f"usage_{tag}.json").write_text(json.dumps(weak_usage, indent=2))
        total_weak_tokens += weak_usage["total_tokens"]
        print(f"done ({weak_usage['total_tokens']} tokens)")

        # GPT-4o (strong)
        print(f"  gpt-4o        ...", end=" ", flush=True)
        strong_text, strong_usage = call_llm(client, "gpt-4o", prompt)
        (strong_dir / f"output_{tag}.txt").write_text(strong_text, encoding="utf-8")
        (strong_dir / f"usage_{tag}.json").write_text(json.dumps(strong_usage, indent=2))
        total_strong_tokens += strong_usage["total_tokens"]
        print(f"done ({strong_usage['total_tokens']} tokens)")

        # Avoid rate limits
        time.sleep(1)

    # Write combined Codex prompts file
    codex_all_path = OUT_DIR / "codex_prompts_all.txt"
    codex_all_path.write_text("\n".join(combined_lines), encoding="utf-8")
    print(f"\nAll 20 Codex prompts written to: {codex_all_path}")

    # Summary
    mini_cost   = (total_weak_tokens   / 1_000_000) * 0.30   # blended gpt-4o-mini rate
    gpt4o_cost  = (total_strong_tokens / 1_000_000) * 5.00   # blended gpt-4o rate

    print("\n" + "="*60)
    print("DONE")
    print("="*60)
    print(f"  gpt-4o-mini : {total_weak_tokens:,} tokens  ~${mini_cost:.4f}")
    print(f"  gpt-4o      : {total_strong_tokens:,} tokens  ~${gpt4o_cost:.4f}")
    print(f"\nPrompt files written to : {prompts_dir}/")
    print(f"Codex placeholders at   : {codex_dir}/")
    print("\nNext steps:")
    print("  1. Paste each prompt_XX.txt into VS Code Codex")
    print("     Save output to results/codex/output_XX.txt")
    print("  2. Run the pipeline on smell_index.json")
    print("  3. Run experiments/evaluate_comparison.py to score all four systems")


if __name__ == "__main__":
    main()
