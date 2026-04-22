# Milestone 3 Presentation Script (~2 minutes, slides 1–4)

---

## Slide 1 — Title

Quick recap before we get into today's results.

---

## Slide 2 — Pipeline Overview

Over the last two milestones, we established two things.

First — React refactoring is genuinely risky. We ran LLMs directly on real Supabase components with generic prompts and found that even GPT-4o drops critical pieces like React context providers. The component looks fine, TypeScript doesn't complain, but the form is silently broken at runtime. So the answer to "can an LLM refactor React components reliably with a generic prompt?" is no.

Second — we built an early agentic version using OpenHands, but it wasn't flexible enough. It was hard to customize, hard to instrument, and the pass rates weren't where we needed them to be for a research paper.

So for Milestone 3, we rebuilt the pipeline from scratch using LangGraph — five nodes, each with a specific job: classify, plan, edit, verify, critique. We added a tactic library with explicit structural invariants, a TypeScript gate, a ReactSniffer re-scan after every edit, and a critique-guided retry loop.

---

## Slide 3 & 4 — Research Questions

That gave us a real system to measure. We defined five research questions to evaluate it:

- **RQ1** — what fraction of detected smells can the pipeline actually act on safely?
- **RQ2** — what's the pass rate, measured by Pass@1 and Pass@2?
- **RQ3** — does the system avoid hallucinated or unsafe edits?
- **RQ4** — what does it cost per task, and does that scale?
- **RQ5** — does the full pipeline beat a single-shot LLM on the same smell?

We ran 100 stratified smells from the Supabase codebase to answer these. Let's look at what we found.

---
