# ReactRefactor

A VS Code extension that detects React code smells and fixes them automatically using an agentic pipeline built with LangGraph.

## How it works

- A custom Babel based detector, **ReactSniffer**, scans your project and flags code smells (large components, too many props, direct DOM manipulation, dead code, and more).
- A local FastAPI server runs a 6 node LangGraph pipeline for each selected smell: classify → plan → edit → verify → critique → finalize, retrying up to 3 times before accepting or rejecting the fix.
- The VS Code extension drives the whole flow: pick smells, watch live progress, review a diff, and revert anything you don't want.

See [extension/README.md](extension/README.md) for the full feature list and usage guide.

## Try it

The packaged extension (`.vsix`) is included in this repo at `extension/react-refactor-0.1.0.vsix`.

1. Download that file (or clone this repo).
2. In VS Code, open the Extensions view, click the `...` menu, and choose **Install from VSIX**.
3. Select the downloaded file.
4. Open the extension settings and add your OpenAI API key.
5. Open a React project, run a scan, and try fixing a smell.

## Evaluation

The pipeline was evaluated on a set of 100 real world code smells, reaching a 74% first attempt success rate, rising to 78% with one retry, at under a cent per fix. It was also tested against real developer commits by rewinding open source repos to the point right before a human fix and solving the same problem blind, which is how a bug in prop removal safety was caught and patched.

## Status

This is a research project and still very much a work in progress. Feedback and suggestions from other developers are welcome.

## Repository layout

- `extension/` — the VS Code extension
- `server/` — the FastAPI backend
- `agentic_refactor_system/` — the LangGraph pipeline and supporting research scaffold
- `experiments/` — evaluation and real commit validation experiments
