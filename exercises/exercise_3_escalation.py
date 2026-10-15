"""Exercise 3: specific reviewer Q&A, then synthesis and publication."""

from __future__ import annotations

import argparse
import hashlib
import os
import uuid
from functools import partial
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from rich.panel import Panel
from rich.text import Text

from common.llm import get_llm
from common.schemas import PRAnalysis
from exercises.exercise_1_confidence import node_fetch_pr, node_route
from exercises.exercise_2_hitl import (
    console,
    node_auto_approve,
    node_human_approval,
    prompt_human,
    write_evidence,
)
from exercises.review_support import analysis_messages, escalation_payload, validate_answers
from exercises.runtime import configure_saver, ensure_github_token, load_environment, publish_review
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
    return {"analysis": PRAnalysis.model_validate(refined), "synthesized": True}


def node_commit(state):
    after_escalation = state.get("decision") == "escalate" and state.get("synthesized")
    if not after_escalation and state.get("human_choice") != "approve":
        console.print("[yellow]skipping comment[/yellow]")
        return {"final_action": "rejected"}
    result = publish_review(state)
    if after_escalation:
        result["final_action"] += "_after_escalation"
    if result["final_action"].startswith("committed"):
        console.print(f"[green]✓ posted comment to {state['pr_url']}[/green]")
    else:
        console.print("[cyan]Preview saved; no GitHub comment posted[/cyan]")
    return result


def build_graph():
    graph = StateGraph(RuntimeState)
    for name, fn in [
        ("fetch_pr", node_fetch_pr),
        ("analyze", node_analyze),
        ("route", node_route),
        ("auto_approve", node_auto_approve),
        ("human_approval", partial(node_human_approval, allow_empty_edit=True)),
        ("escalate", node_escalate),
        ("synthesize", node_synthesize),
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
    graph.add_edge("escalate", "synthesize")
    graph.add_edge("synthesize", "commit")
    graph.add_edge("human_approval", "commit")
    graph.add_edge("commit", END)
    graph.add_edge("auto_approve", END)
    return graph.compile(checkpointer=configure_saver(MemorySaver()))


def handle_interrupt(payload, *, allow_empty_edit=False):
    if payload["kind"] == "approval_request":
        return prompt_human(payload, allow_empty_edit=allow_empty_edit)
    if payload["kind"] != "escalation":
        raise ValueError("Unknown interrupt kind")
    content = Text(payload["pr_url"] + "\n\n")
    content.append("Reasoning: " + payload["confidence_reasoning"] + "\n\n")
    content.append("Summary: " + payload["summary"] + "\n\n")
    content.append("Risks:\n" + "\n".join(payload.get("risk_factors", [])))
    console.print(
        Panel(content, title=f"Escalation conf={payload['confidence']:.0%}", border_style="yellow")
    )
    while True:
        answers = {q: console.input(Text(f"Q: {q}\nA: ")).strip() for q in payload["questions"]}
        try:
            return validate_answers(payload, answers)
        except ValueError as error:
            console.print(str(error), markup=False)


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true", help="Publish the review (lab default)")
    mode.add_argument("--preview", action="store_true", help="Synthesize a draft without posting")
    parser.add_argument("--evidence", help="Save graph snapshots and pending payload as JSON")
    args = parser.parse_args()
    ensure_github_token()
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    publish_mode = "preview" if args.preview else "live"
    console.print(
        "[yellow]Escalation answers will synthesize and post a public GitHub comment.[/yellow]"
        if publish_mode == "live"
        else "[cyan]Preview mode; no GitHub comment will be posted.[/cyan]"
    )
    root = Path(__file__).resolve().parents[1]
    sources = [*sorted((root / "exercises").glob("*.py")), *sorted((root / "common").glob("*.py"))]
    record = {
        "format_version": 1,
        "exercise": 3,
        "pr_url": args.pr,
        "thread_id": thread_id,
        "checkpointer": "MemorySaver (in-process only)",
        "publish_mode": publish_mode,
        "llm_model_requested": os.environ.get("LLM_MODEL"),
        "llm_base_url": os.environ.get("LLM_BASE_URL"),
        "source_hashes": {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
        "snapshots": [],
        "responses": [],
    }
    graph = build_graph()
    result = graph.invoke(
        {
            "pr_url": args.pr,
            "thread_id": thread_id,
            "publish_mode": publish_mode,
        },
        cfg,
    )
    write_evidence(args.evidence, result, record)
    while "__interrupt__" in result:
        answer = handle_interrupt(result["__interrupt__"][0].value, allow_empty_edit=True)
        record["responses"].append(answer)
        result = graph.invoke(Command(resume=answer), cfg)
        write_evidence(args.evidence, result, record)
    console.rule("Final")
    console.print("final_action =", result.get("final_action"))
    console.print(f"final confidence = {result['analysis'].confidence:.0%}")


if __name__ == "__main__":
    main()
