"""Exercise 2: checkpointed approve/reject/edit with interrupt and Command."""

from __future__ import annotations

import argparse
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from rich.console import Console
from rich.panel import Panel

from exercises.exercise_1_confidence import node_analyze, node_fetch_pr, node_route
from exercises.review_support import approval_payload, render_comment_body, validate_choice
from exercises.runtime import ensure_github_token, load_environment, publish_review
from exercises.state import RuntimeState

console = Console()


def node_human_approval(state):
    return validate_choice(interrupt(approval_payload(state)))


def node_edit(state):
    return {"edited_review": state["human_feedback"], "human_choice": None}


def node_confirm_edit(state):
    payload = {**approval_payload(state), "summary": state["edited_review"], "comments": []}
    return validate_choice(interrupt(payload))


def node_commit(state):
    if state.get("human_choice") != "approve":
        return {"final_action": "rejected"}
    return publish_review(state)


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
        ("human_approval", node_human_approval),
        ("auto_approve", node_auto_approve),
        ("escalate", node_escalate),
        ("commit", node_commit),
        ("edit", node_edit),
        ("confirm_edit", node_confirm_edit),
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
    for node in ("human_approval", "confirm_edit"):
        graph.add_conditional_edges(
            node, lambda s: "edit" if s["human_choice"] == "edit" else "commit"
        )
    graph.add_edge("edit", "confirm_edit")
    for node in ("commit", "auto_approve", "escalate"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=MemorySaver())


def prompt_human(payload):
    console.print(Panel(payload["summary"], title=f"Approval — {payload['confidence']:.0%}"))
    console.print(payload["confidence_reasoning"], markup=False)
    console.print(payload.get("diff_preview", ""), markup=False)
    for comment in payload.get("comments", []):
        console.print(f"{comment['severity']} {comment['file']}: {comment['body']}", markup=False)
    while True:
        choice = console.input("approve/reject/edit? ").strip().lower()
        feedback = (
            console.input("Replacement review / feedback: ").strip() if choice != "approve" else ""
        )
        response = {"choice": choice, "feedback": feedback}
        try:
            validate_choice(response)
            return response
        except ValueError as error:
            console.print(str(error), markup=False)


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True)
    parser.add_argument(
        "--publish", action="store_true", help="Actually post the final comment to GitHub"
    )
    args = parser.parse_args()
    ensure_github_token()
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    app = build_graph()
    result = app.invoke(
        {
            "pr_url": args.pr,
            "thread_id": thread_id,
            "publish_mode": "live" if args.publish else "preview",
        },
        cfg,
    )
    while "__interrupt__" in result:
        result = app.invoke(Command(resume=prompt_human(result["__interrupt__"][0].value)), cfg)
    console.print(result.get("final_action"))


if __name__ == "__main__":
    main()
