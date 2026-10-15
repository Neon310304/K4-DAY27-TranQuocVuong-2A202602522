"""Exercise 2: pause for approval; reject/edit both skip publication.

The edit/confirm helpers are used by Exercise 3, which extends this graph.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from exercises.exercise_1_confidence import node_analyze, node_fetch_pr, node_route
from exercises.review_support import approval_payload, render_comment_body, validate_choice
from exercises.runtime import ensure_github_token, load_environment, publish_review
from exercises.state import RuntimeState

console = Console()


def node_human_approval(state, *, allow_empty_edit=False):
    payload = approval_payload(state)
    payload["diff_preview"] = payload["diff_preview"][:2000]
    return validate_choice(interrupt(payload), allow_empty_edit=allow_empty_edit)


def node_edit(state):
    return {"edited_review": state["human_feedback"], "human_choice": None}


def node_confirm_edit(state):
    payload = {**approval_payload(state), "summary": state["edited_review"], "comments": []}
    return validate_choice(interrupt(payload))


def node_commit(state):
    if state.get("human_choice") != "approve":
        console.print("[yellow]skipping comment[/yellow]")
        return {"final_action": "rejected"}
    result = publish_review(state)
    if result["final_action"] == "committed":
        console.print(f"[green]✓ posted comment to {state['pr_url']}[/green]")
    else:
        console.print("[cyan]Preview saved; no GitHub comment posted[/cyan]")
    return result


def node_auto_approve(state):
    return publish_review(state)


def node_escalate(state):
    return {"final_action": "pending_escalation"}


def _render_comment_body(state):
    return render_comment_body(state)


def build_graph():
    graph = StateGraph(RuntimeState)
    for name, fn in [
        ("fetch_pr", node_fetch_pr),
        ("analyze", node_analyze),
        ("route", node_route),
        ("human_approval", partial(node_human_approval, allow_empty_edit=True)),
        ("auto_approve", node_auto_approve),
        ("escalate", node_escalate),
        ("commit", node_commit),
    ]:
        graph.add_node(name, fn)
    graph.add_edge(START, "fetch_pr")
    graph.add_edge("fetch_pr", "analyze")
    graph.add_edge("analyze", "route")
    graph.add_conditional_edges(
        "route",
        lambda s: s["decision"],
        {n: n for n in ("auto_approve", "human_approval", "escalate")},
    )
    graph.add_edge("human_approval", "commit")
    for node in ("commit", "auto_approve", "escalate"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=MemorySaver())


def prompt_human(payload, *, allow_empty_edit=False):
    content = Text(f"Confidence: {payload['confidence']:.0%}\n\n")
    content.append("Reasoning: " + payload["confidence_reasoning"] + "\n\n")
    content.append("Summary: " + payload["summary"] + "\n\n")
    content.append("Proposed comments:\n")
    for comment in payload.get("comments", []):
        content.append(
            f"[{comment['severity']}] {comment['file']}:{comment.get('line') or '?'}: "
            + comment["body"]
            + "\n"
        )
    content.append("\nDiff preview (first 2,000 characters):\n" + payload.get("diff_preview", ""))
    console.print(Panel(content, title="Approval request", border_style="green"))
    while True:
        choice = console.input("Choice (approve/reject/edit)? ").strip().lower()
        feedback = ""
        if choice in {"reject", "edit"}:
            label = (
                "Feedback (optional; this exercise does not apply edits): "
                if allow_empty_edit
                else "Replacement review / feedback: "
            )
            feedback = console.input(label).strip()
        response = {"choice": choice, "feedback": feedback}
        try:
            validate_choice(response, allow_empty_edit=allow_empty_edit)
            return response
        except ValueError as error:
            console.print(str(error), markup=False)


def write_evidence(path, result, record):
    """Export only graph data; credentials and other environment values stay private."""
    if not path:
        return
    state = {key: value for key, value in result.items() if key != "__interrupt__"}
    if state.get("analysis"):
        state["analysis"] = state["analysis"].model_dump(mode="json")
    record["snapshots"].append(state)
    record["pending_payload"] = (
        result["__interrupt__"][0].value if result.get("__interrupt__") else None
    )
    record["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true", help="Post after approval (lab default)")
    mode.add_argument(
        "--preview", action="store_true", help="Keep approved review as a local draft"
    )
    parser.add_argument("--evidence", help="Save graph snapshots and pending payload as JSON")
    args = parser.parse_args()
    ensure_github_token()
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    publish_mode = "preview" if args.preview else "live"
    console.print(
        "[yellow]Approve will post a public GitHub comment.[/yellow]"
        if publish_mode == "live"
        else "[cyan]Preview mode; no GitHub comment will be posted.[/cyan]"
    )
    record = {
        "format_version": 1,
        "exercise": 2,
        "pr_url": args.pr,
        "thread_id": thread_id,
        "checkpointer": "MemorySaver (in-process only)",
        "publish_mode": publish_mode,
        "llm_model_requested": os.environ.get("LLM_MODEL"),
        "llm_base_url": os.environ.get("LLM_BASE_URL"),
        "snapshots": [],
        "responses": [],
    }
    app = build_graph()
    result = app.invoke(
        {
            "pr_url": args.pr,
            "thread_id": thread_id,
            "publish_mode": publish_mode,
        },
        cfg,
    )
    write_evidence(args.evidence, result, record)
    while "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        answer = prompt_human(payload, allow_empty_edit=True)
        record["responses"].append(answer)
        result = app.invoke(Command(resume=answer), cfg)
        write_evidence(args.evidence, result, record)
    console.rule("Done")
    console.print("final_action =", result.get("final_action"))


if __name__ == "__main__":
    main()
