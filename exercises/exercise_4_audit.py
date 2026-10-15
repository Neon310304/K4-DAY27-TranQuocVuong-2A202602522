"""Exercise 4: durable sessions and one structured audit row per node execution.

Interrupt nodes log pending before interrupt and the response after it. Resuming
replays the node, so its pre-interrupt pending row is intentionally repeated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from common.db import write_audit_event
from common.schemas import AuditEntry, risk_level_for
from exercises.exercise_3_escalation import handle_interrupt
from exercises.review_support import (
    approval_payload,
    escalation_payload,
    route_for,
    validate_answers,
    validate_choice,
)
from exercises.runtime import (
    analyze_with,
    backend_for,
    load_environment,
    new_thread,
    publish_review,
    run_session,
)
from exercises.state import RuntimeState

AGENT_ID = "pr-review-agent@v1.0"
AUDIT_DECISIONS = frozenset({"auto", "approve", "reject", "edit", "escalate", "pending"})


async def audit(state, entry: AuditEntry) -> None:
    await write_audit_event(thread_id=state["thread_id"], pr_url=state["pr_url"], entry=entry)


def entry_for(state, action, decision, started, reason, *, human=False, analysis=None):
    if decision not in AUDIT_DECISIONS:
        raise ValueError(f"Unsupported audit decision: {decision}")
    analysis = analysis or state.get("analysis")
    confidence = analysis.confidence if analysis else 0.0
    return AuditEntry(
        agent_id=AGENT_ID,
        action=action,
        confidence=confidence,
        risk_level=risk_level_for(confidence) if analysis else "med",
        reviewer_id=os.environ.get("GITHUB_USER") if human else None,
        decision=decision,
        reason=reason,
        execution_time_ms=max(0, int((time.monotonic() - started) * 1000)),
    )


async def node_fetch_pr(state, *, backend=None):
    started = time.monotonic()
    pr = await asyncio.to_thread(backend_for(state, backend).fetch, state["pr_url"])
    await audit(
        state,
        entry_for(
            state,
            "fetch_pr",
            "pending",
            started,
            f"Fetched {len(pr.files_changed)} files; head={pr.head_sha}",
        ),
    )
    return {
        "pr_title": pr.title,
        "pr_author": pr.author,
        "pr_diff": pr.diff,
        "pr_files": pr.files_changed,
        "pr_head_sha": pr.head_sha,
    }


async def node_analyze(state, *, backend=None):
    started = time.monotonic()
    analysis = await analyze_with(backend_for(state, backend), state)
    await audit(
        state,
        entry_for(
            state, "analyze", "pending", started, analysis.confidence_reasoning, analysis=analysis
        ),
    )
    return {"analysis": analysis}


async def node_route(state):
    started = time.monotonic()
    decision = route_for(state["analysis"].confidence)
    audit_decision = {
        "auto_approve": "auto",
        "human_approval": "pending",
        "escalate": "escalate",
    }[decision]
    await audit(
        state,
        entry_for(state, "route", audit_decision, started, state["analysis"].confidence_reasoning),
    )
    return {"decision": decision}


async def node_human_approval(state):
    started = time.monotonic()
    payload = approval_payload(state)
    if state.get("edited_review"):
        payload.update(summary=state["edited_review"], comments=[])
    payload["refined"] = bool(state.get("synthesized"))
    payload["edited"] = bool(state.get("edited_review"))
    pending = entry_for(
        state,
        "human_approval",
        "pending",
        started,
        f"Awaiting final review decision; round={state.get('approval_round', 0)}",
    )
    await audit(state, pending)
    response = interrupt(payload)
    result = validate_choice(response)
    await audit(
        state,
        entry_for(
            state,
            "human_approval",
            result["human_choice"],
            started,
            result["human_feedback"] or f"Reviewer chose {result['human_choice']}",
            human=True,
        ),
    )
    return result


async def node_edit(state):
    started = time.monotonic()
    await audit(
        state,
        entry_for(
            state,
            "edit",
            "edit",
            started,
            "Replacement review saved; awaiting confirmation",
            human=True,
        ),
    )
    return {
        "edited_review": state["human_feedback"],
        "human_choice": None,
        "approval_round": state.get("approval_round", 0) + 1,
    }


async def node_escalate(state):
    started = time.monotonic()
    payload = escalation_payload(state)
    pending = entry_for(
        state,
        "escalate",
        "pending",
        started,
        "Awaiting reviewer context: " + json.dumps(payload["questions"], ensure_ascii=False),
    )
    await audit(state, pending)
    answers = validate_answers(payload, interrupt(payload))
    await audit(
        state,
        entry_for(
            state,
            "escalate",
            "escalate",
            started,
            json.dumps(answers, ensure_ascii=False),
            human=True,
        ),
    )
    return {"escalation_answers": answers}


async def node_synthesize(state, *, backend=None):
    started = time.monotonic()
    refined = await analyze_with(backend_for(state, backend), state, refine=True)
    await audit(
        state,
        entry_for(
            state, "synthesize", "pending", started, refined.confidence_reasoning, analysis=refined
        ),
    )
    return {"analysis": refined, "synthesized": True, "human_choice": None}


async def node_auto_approve(state):
    started = time.monotonic()
    await audit(
        state,
        entry_for(
            state,
            "auto_approve",
            "auto",
            started,
            "Confidence meets the automatic routing threshold",
        ),
    )
    return {"human_choice": None}


async def node_commit(state, *, backend=None):
    started = time.monotonic()
    automatic = state.get("decision") == "auto_approve" and not state.get("synthesized")
    approved = automatic or state.get("human_choice") == "approve"
    if not approved:
        result = {"final_action": "rejected", "posted_comment_body": None, "comment_url": None}
    else:
        try:
            result = await asyncio.to_thread(
                publish_review, state, getattr(backend, "post", None) if backend else None
            )
            if automatic:
                result["final_action"] = "auto_" + result["final_action"]
        except Exception as error:
            # Provider exceptions may contain request headers. Persist only class/status.
            status = getattr(getattr(error, "response", None), "status_code", None)
            result = {
                "final_action": "commit_failed",
                "comment_url": None,
                "publish_error": f"{type(error).__name__}"
                + (f" (HTTP {status})" if status else ""),
            }
    action = result["final_action"]
    audit_decision = (
        "pending"
        if action == "commit_failed"
        else "auto"
        if automatic
        else "approve"
        if approved
        else "reject"
    )
    await audit(
        state,
        entry_for(
            state,
            "commit",
            audit_decision,
            started,
            f"{action}; " + (result.get("publish_error") or "final decision processed"),
            human=not automatic,
        ),
    )
    return result


def build_graph(checkpointer, *, backend=None):
    graph = StateGraph(RuntimeState)
    graph.add_node("fetch_pr", partial(node_fetch_pr, backend=backend))
    graph.add_node("analyze", partial(node_analyze, backend=backend))
    graph.add_node("synthesize", partial(node_synthesize, backend=backend))
    graph.add_node("commit", partial(node_commit, backend=backend))
    for name, fn in [
        ("route", node_route),
        ("human_approval", node_human_approval),
        ("auto_approve", node_auto_approve),
        ("escalate", node_escalate),
        ("edit", node_edit),
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
    graph.add_edge("auto_approve", "commit")
    graph.add_edge("escalate", "synthesize")
    graph.add_edge("synthesize", "human_approval")
    graph.add_conditional_edges(
        "human_approval", lambda s: "edit" if s["human_choice"] == "edit" else "commit"
    )
    graph.add_edge("edit", "human_approval")
    graph.add_edge("commit", END)
    return graph.compile(checkpointer=checkpointer)


async def run(pr_url, thread_id=None, *, demo=False, publish=False):
    thread_id = thread_id or new_thread()
    print(f"thread_id = {thread_id}")
    result = await run_session(
        pr_url,
        thread_id,
        backend_mode="demo" if demo else "live",
        publish_mode="live" if publish else "preview",
    )
    while result.get("interrupt_payload"):
        answer = handle_interrupt(result["interrupt_payload"])
        result = await run_session(pr_url, thread_id, answer)
    print("final_action =", result.get("final_action"))
    print(f"Replay: uv run python -m audit.replay --thread {thread_id}")
    return result


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True)
    parser.add_argument(
        "--thread", help="Reopen the persisted session; never refetches or reanalyzes"
    )
    parser.add_argument("--demo", action="store_true", help="Synthetic offline fixtures, no APIs")
    parser.add_argument("--publish", action="store_true", help="Post comments to GitHub")
    args = parser.parse_args()
    asyncio.run(run(args.pr, args.thread, demo=args.demo, publish=args.publish))


if __name__ == "__main__":
    main()
