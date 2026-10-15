"""Runtime adapters, safe preview publication, and persistent UI session operations."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from common.db import db_conn, db_path
from common.github import fetch_pr, post_review_comment
from common.llm import get_llm
from common.schemas import PRAnalysis, ReviewState
from exercises.review_support import (
    DemoBackend,
    analysis_messages,
    render_comment_body,
    validate_pr_url,
)

ROOT = Path(__file__).resolve().parents[1]


def configure_saver(checkpointer):
    """Explicitly allow only the lab's Pydantic types in stored checkpoints."""
    checkpointer.serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("common.schemas", "PRAnalysis"),
            ("common.schemas", "ReviewComment"),
        ]
    )
    return checkpointer


def load_environment() -> None:
    load_dotenv(ROOT / ".env")
    # The provided factory keeps its OpenRouter variable names. Accept the
    # OpenAI-compatible names used by YesScale without changing common/.
    for canonical, aliases in {
        "OPENROUTER_API_KEY": ("OPENAI_API_KEY", "YESCALE_API_KEY"),
        "LLM_BASE_URL": ("OPENAI_BASE_URL", "YESCALE_BASE_URL"),
        "LLM_MODEL": ("OPENAI_MODEL",),
    }.items():
        if not os.environ.get(canonical):
            for alias in aliases:
                if os.environ.get(alias):
                    os.environ[canonical] = os.environ[alias]
                    break


def ensure_github_token() -> None:
    """Use an existing Git credential in memory, with interactive prompts disabled."""
    if os.environ.get("GITHUB_TOKEN"):
        return
    cached_token = os.environ.get("GH_TOKEN")
    if not cached_token:
        try:
            result = subprocess.run(
                ["git", "credential", "fill"],
                input="protocol=https\nhost=github.com\n\n",
                capture_output=True,
                text=True,
                timeout=15,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
            )
            fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            if result.returncode == 0:
                cached_token = fields.get("password")
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not cached_token:
        raise RuntimeError(
            "Set GITHUB_TOKEN in .env (public_repo scope). No usable Git credential was found."
        )
    os.environ["GITHUB_TOKEN"] = cached_token


class LiveBackend:
    def fetch(self, url: str):
        ensure_github_token()
        return fetch_pr(validate_pr_url(url))

    def analyze(self, state: ReviewState, *, refine: bool = False) -> PRAnalysis:
        return PRAnalysis.model_validate(
            get_llm()
            .with_structured_output(PRAnalysis)
            .invoke(analysis_messages(state, refine=refine))
        )

    async def aanalyze(self, state: ReviewState, *, refine: bool = False) -> PRAnalysis:
        return PRAnalysis.model_validate(
            await get_llm()
            .with_structured_output(PRAnalysis)
            .ainvoke(analysis_messages(state, refine=refine))
        )


def publication_mode(state: dict) -> str:
    if state.get("backend_mode") == "demo":
        return "preview"
    mode = state.get("publish_mode") or os.environ.get("HITL_PUBLISH_MODE", "preview")
    if mode not in {"preview", "live"}:
        raise ValueError("HITL_PUBLISH_MODE must be preview or live")
    return mode


def publish_review(state: dict, poster: Callable | None = None) -> dict:
    """Preview is a real local draft, not a claim that GitHub received a comment."""
    body = render_comment_body(state)
    result = {"posted_comment_body": body, "comment_url": None}
    if publication_mode(state) == "preview":
        return {**result, "final_action": "previewed"}
    ensure_github_token()
    # Keep a stable marker in the published body. Crash-safe exactly-once delivery
    # across GitHub and SQLite would require an outbox/reconciliation service.
    digest = hashlib.sha256(
        f"{state.get('thread_id', '')}:{state.get('pr_head_sha', '')}".encode()
    ).hexdigest()[:24]
    body += f"\n\n<!-- day27-review:{digest} -->"
    (poster or post_review_comment)(state["pr_url"], body)
    return {
        "posted_comment_body": body,
        "comment_url": state["pr_url"],
        "final_action": "committed",
    }


def interrupt_from(snapshot) -> dict | None:
    for task in snapshot.tasks:
        for pending in task.interrupts:
            return pending.value
    return None


def snapshot_result(snapshot) -> dict:
    result = dict(snapshot.values)
    payload = interrupt_from(snapshot)
    if payload:
        result["interrupt_payload"] = payload
    return result


async def run_session(
    pr_url: str,
    thread_id: str,
    resume_value=None,
    *,
    backend_mode: str = "live",
    publish_mode: str = "preview",
    backend=None,
) -> dict:
    """Reopen the same saver on every request; loading an existing thread never restarts it."""
    from exercises.exercise_4_audit import build_graph

    load_environment()
    async with AsyncSqliteSaver.from_conn_string(db_path()) as cp:
        configure_saver(cp)
        await cp.setup()
        graph = build_graph(cp, backend=backend)
        cfg = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(cfg)
        if snapshot.values:
            if snapshot.values["pr_url"] != pr_url:
                raise ValueError("This session belongs to another PR")
            if not snapshot.next:
                return snapshot_result(snapshot)
            pending = interrupt_from(snapshot)
            if resume_value is None:
                if pending:
                    return snapshot_result(snapshot)
                await graph.ainvoke(None, cfg)  # resume a failed/interrupted process
            else:
                if not pending:
                    raise ValueError("This session has no pending human decision")
                from exercises.review_support import validate_answers, validate_choice

                if pending["kind"] == "approval_request":
                    validate_choice(resume_value)
                else:
                    validate_answers(pending, resume_value)
                await graph.ainvoke(Command(resume=resume_value), cfg)
        else:
            if resume_value is not None:
                raise ValueError("Cannot resume a session that does not exist")
            validate_pr_url(pr_url)
            await graph.ainvoke(
                {
                    "pr_url": pr_url,
                    "thread_id": thread_id,
                    "backend_mode": backend_mode,
                    "publish_mode": publish_mode,
                },
                cfg,
            )
        return snapshot_result(await graph.aget_state(cfg))


async def load_session(thread_id: str) -> dict:
    from exercises.exercise_4_audit import build_graph

    async with AsyncSqliteSaver.from_conn_string(db_path()) as cp:
        configure_saver(cp)
        await cp.setup()
        graph = build_graph(cp)
        return snapshot_result(await graph.aget_state({"configurable": {"thread_id": thread_id}}))


async def recent_sessions() -> list[dict]:
    async with (
        db_conn() as conn,
        conn.execute("""
            SELECT thread_id, pr_url, MIN(timestamp) AS started, MAX(timestamp) AS last_event,
                   MAX(CASE risk_level WHEN 'high' THEN 3 WHEN 'med' THEN 2 ELSE 1 END) AS risk,
                   COUNT(*) AS events
              FROM audit_events GROUP BY thread_id ORDER BY last_event DESC LIMIT 25
        """) as cursor,
    ):
        return [dict(row) for row in await cursor.fetchall()]


def new_thread() -> str:
    return str(uuid.uuid4())


async def audit_pending_once(state: dict, entry) -> bool:
    """interrupt() replays its node. Avoid repeating its pre-interrupt audit row."""
    async with db_conn() as conn:
        async with conn.execute(
            "SELECT 1 FROM audit_events WHERE thread_id=? AND action=? AND decision=? AND reason=? LIMIT 1",
            (state["thread_id"], entry.action, entry.decision, entry.reason),
        ) as cursor:
            return await cursor.fetchone() is not None


def backend_for(state: dict, injected=None):
    return injected or (DemoBackend() if state.get("backend_mode") == "demo" else LiveBackend())


async def analyze_with(backend, state: dict, *, refine: bool = False) -> PRAnalysis:
    if hasattr(backend, "aanalyze"):
        value = await backend.aanalyze(state, refine=refine)
    else:
        value = await asyncio.to_thread(backend.analyze, state, refine=refine)
    return PRAnalysis.model_validate(value)
