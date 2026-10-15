"""Exercise 3: specific reviewer Q&A, synthesis, and final confirmation."""

from __future__ import annotations

import argparse
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from common.llm import get_llm
from common.schemas import PRAnalysis
from exercises.exercise_1_confidence import node_fetch_pr, node_route
from exercises.exercise_2_hitl import (
    console,
    node_auto_approve,
    node_commit,
    node_confirm_edit,
    node_edit,
    node_human_approval,
    prompt_human,
)
from exercises.review_support import analysis_messages, escalation_payload, validate_answers
from exercises.runtime import ensure_github_token, load_environment
from exercises.state import RuntimeState


def node_analyze(state):
    analysis = get_llm().with_structured_output(PRAnalysis).invoke(analysis_messages(state))
    return {"analysis": PRAnalysis.model_validate(analysis)}


def node_escalate(state):
    payload = escalation_payload(state)
    return {"escalation_answers": validate_answers(payload, interrupt(payload))}


def node_synthesize(state):
    refined = (
        get_llm().with_structured_output(PRAnalysis).invoke(analysis_messages(state, refine=True))
    )
    return {"analysis": PRAnalysis.model_validate(refined), "human_choice": None}


def build_graph():
    graph = StateGraph(RuntimeState)
    for name, fn in [
        ("fetch_pr", node_fetch_pr),
        ("analyze", node_analyze),
        ("route", node_route),
        ("auto_approve", node_auto_approve),
        ("human_approval", node_human_approval),
        ("escalate", node_escalate),
        ("synthesize", node_synthesize),
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
    graph.add_edge("escalate", "synthesize")
    graph.add_edge("synthesize", "human_approval")
    for name in ("human_approval", "confirm_edit"):
        graph.add_conditional_edges(
            name, lambda s: "edit" if s["human_choice"] == "edit" else "commit"
        )
    graph.add_edge("edit", "confirm_edit")
    graph.add_edge("commit", END)
    graph.add_edge("auto_approve", END)
    return graph.compile(checkpointer=MemorySaver())


def handle_interrupt(payload):
    if payload["kind"] == "approval_request":
        return prompt_human(payload)
    if payload["kind"] != "escalation":
        raise ValueError("Unknown interrupt kind")
    console.print(payload["summary"], markup=False)
    console.print("\n".join(payload.get("risk_factors", [])), markup=False)
    while True:
        answers = {q: console.input(f"Q: {q}\nA: ").strip() for q in payload["questions"]}
        try:
            return validate_answers(payload, answers)
        except ValueError as error:
            console.print(str(error), markup=False)


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    ensure_github_token()
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    graph = build_graph()
    result = graph.invoke(
        {
            "pr_url": args.pr,
            "thread_id": thread_id,
            "publish_mode": "live" if args.publish else "preview",
        },
        cfg,
    )
    while "__interrupt__" in result:
        result = graph.invoke(
            Command(resume=handle_interrupt(result["__interrupt__"][0].value)), cfg
        )
    console.print(result.get("final_action"))


if __name__ == "__main__":
    main()
