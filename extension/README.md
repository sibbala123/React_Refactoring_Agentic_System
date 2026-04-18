# ReactRefactor

Agentic code smell detection and automated refactoring for React projects, powered by LangGraph and OpenAI.

## Prerequisites

- **Python 3.8+** — must be on your PATH or managed by the ms-python extension
- **OpenAI API key** — set `OPENAI_API_KEY` in your environment
- **Git** — required for diff and revert features

## Features

- **Scan** — detects React code smells (Large Component, Too Many Props, JSX Outside Render, etc.) using ReactSniffer
- **Fix** — runs a 6-node LangGraph pipeline (classify → plan → edit → verify → critique → finalize) to refactor selected smells
- **Live progress** — real-time SSE updates per pipeline node
- **Fix Report** — summary panel with accepted/rejected/skipped/failed counts and error details
- **Inline Diff** — click an accepted smell to see original vs refactored side-by-side
- **Revert** — revert individual fixes or all accepted fixes back to git HEAD

## Usage

1. Open a React project folder in VS Code
2. Click the **ReactRefactor** icon in the Activity Bar
3. Click the **Scan** button (magnifying glass) to detect smells
4. Check the smells you want to fix
5. Click the **Fix Selected** button (wrench) and confirm the cost/time estimate
6. Monitor live progress in the sidebar and Output Channel
7. When complete, review the Fix Report — click accepted smells for a diff, or revert unwanted changes

## First Run

On first activation, ReactRefactor will automatically install required Python packages (`pip install -r requirements.txt`). This takes ~30 seconds. Subsequent activations skip this step.

If Python is not found, use the **Select Python Interpreter** button in the error notification.

## Supported Smell Types

| Smell | Severity |
|---|---|
| Large Component | High |
| Too Many Props | High |
| Direct DOM Manipulation | Medium |
| Force Update | Medium |
| JSX Outside the Render Method | Medium |
| Inheritance Instead of Composition | Medium |
| Props in Initial State | Low |
| Uncontrolled Component | Low |
