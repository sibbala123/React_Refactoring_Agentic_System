"""Execute one OpenHands refactor or critique task inside the local SDK venv."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from openhands.sdk import Agent, Conversation, LLM, Tool
from openhands.sdk.conversation import get_agent_final_response
from openhands.sdk.event import MessageEvent
from openhands.sdk.llm.message import content_to_str
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool

try:
    from openhands.tools.delegate import DelegateTool
except Exception:  # pragma: no cover
    DelegateTool = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["refactor", "critique"], required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--response-file", required=True)
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--model", default="gpt-5.2-codex")
    parser.add_argument("--max-iterations", type=int, default=80)
    parser.add_argument("--use-delegate", action="store_true")
    parser.add_argument("--force-login", action="store_true")
    return parser.parse_args()


def extract_assistant_text_from_events(events: list[Any]) -> str:
    final_text = get_agent_final_response(events)
    if final_text and final_text.strip():
        return final_text.strip()

    parts: list[str] = []
    for event in events:
        if isinstance(event, MessageEvent) and getattr(event, "source", None) == "agent":
            llm_message = getattr(event, "llm_message", None)
            if llm_message is None:
                continue
            text = "".join(content_to_str(llm_message.content)).strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def event_to_text(event: Any) -> str:
    lines = [f"type={type(event).__name__}"]
    for field in ("source", "action", "observation", "tool_name"):
        value = getattr(event, field, None)
        if value is not None:
            lines.append(f"{field}={value}")

    llm_message = getattr(event, "llm_message", None)
    if llm_message is not None:
        role = getattr(llm_message, "role", None)
        if role is not None:
            lines.append(f"role={role}")
        content = getattr(llm_message, "content", None)
        if content is not None:
            try:
                text = "".join(content_to_str(content)).strip()
            except Exception:
                text = str(content)
            if text:
                lines.append("content:")
                lines.append(text)

    thought = getattr(event, "thought", None)
    if thought:
        lines.append("thought:")
        lines.append(str(thought))
    return "\n".join(lines)


def write_event_transcript(events: list[Any], out_file: Path, final_text: str) -> None:
    chunks: list[str] = []
    for index, event in enumerate(events):
        chunks.append(f"--- EVENT {index} ---")
        chunks.append(event_to_text(event))
        chunks.append("")
    chunks.append("=== FINAL_EXTRACTED_RESPONSE ===")
    chunks.append(final_text)
    out_file.write_text("\n".join(chunks), encoding="utf-8")


def normalize_critique_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    try:
        obj = json.loads(text)
    except Exception:
        return {
            "acceptable": False,
            "score": 0.0,
            "issues": ["Critique agent returned invalid JSON."],
            "recommendations": ["Return valid critique JSON only."],
            "summary": "Critique output invalid.",
        }

    return {
        "acceptable": bool(obj.get("acceptable", False)),
        "score": float(obj.get("score", 0.0)),
        "issues": [str(item) for item in obj.get("issues", []) if isinstance(item, (str, int, float))],
        "recommendations": [
            str(item) for item in obj.get("recommendations", []) if isinstance(item, (str, int, float))
        ],
        "summary": str(obj.get("summary", "")).strip(),
    }


def build_llm(model: str, force_login: bool = False) -> LLM:
    return LLM.subscription_login(
        vendor="openai",
        model=model,
        open_browser=False,
        force_login=force_login,
        prompt_cache_retention=None,
    )


def build_agent(mode: str, llm: LLM, use_delegate: bool) -> Agent:
    if mode == "critique":
        return Agent(llm=llm, tools=[])

    tools = [
        Tool(name=FileEditorTool.name),
        Tool(name=TaskTrackerTool.name),
    ]
    if use_delegate and DelegateTool is not None:
        tools.append(Tool(name=DelegateTool.name))
    return Agent(llm=llm, tools=tools)


def run_task(args: argparse.Namespace) -> dict[str, Any]:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
    llm = build_llm(args.model, force_login=args.force_login)
    agent = build_agent(args.mode, llm, args.use_delegate)
    captured_events: list[Any] = []

    def _capture_event(event: Any) -> None:
        captured_events.append(event)

    conversation = Conversation(
        agent=agent,
        workspace=args.workspace,
        callbacks=[_capture_event],
        visualizer=None,
        max_iteration_per_run=args.max_iterations,
    )
    conversation.send_message(prompt_text)
    conversation.run()

    response_text = extract_assistant_text_from_events(captured_events)
    response_path = Path(args.response_file)
    response_path.write_text(response_text + ("\n" if response_text else ""), encoding="utf-8")
    write_event_transcript(captured_events, Path(args.events_file), response_text)

    result: dict[str, Any] = {
        "status": "completed",
        "mode": args.mode,
        "model": args.model,
        "workspace": args.workspace,
        "event_count": len(captured_events),
        "response_file": str(response_path),
        "events_file": args.events_file,
        "response_text": response_text,
        "accumulated_cost": float(getattr(llm.metrics, "accumulated_cost", 0.0) or 0.0),
    }
    if args.mode == "critique":
        result["critique"] = normalize_critique_json(response_text)

    result_path = Path(args.result_file)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    run_task(parse_args())


if __name__ == "__main__":
    main()
