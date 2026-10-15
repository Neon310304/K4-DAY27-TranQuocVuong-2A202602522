"""Behavioral tests run offline against real LangGraph and SQLite checkpoints."""

from pathlib import Path

import pytest
from langgraph.types import Command
from streamlit.testing.v1 import AppTest

from common.db import replay_events
from common.schemas import PRAnalysis
from exercises import exercise_1_confidence as ex1
from exercises import exercise_2_hitl as ex2
from exercises import exercise_3_escalation as ex3
from exercises.review_support import (
    DemoBackend,
    analysis_messages,
    escalation_payload,
    render_comment_body,
    route_for,
    validate_pr_url,
)
from exercises.runtime import load_session, publish_review, run_session


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("HITL_DB_PATH", str(tmp_path / "review.db"))
    monkeypatch.setenv("GITHUB_USER", "fixture-reviewer")
    monkeypatch.setenv("HITL_PUBLISH_MODE", "preview")


def url(number=1):
    return f"https://github.com/demo/shop/pull/{number}"


@pytest.mark.parametrize(
    "score,expected",
    [
        (0, "escalate"),
        (0.5799, "escalate"),
        (0.58, "human_approval"),
        (0.72, "human_approval"),
        (0.7299, "human_approval"),
        (0.73, "auto_approve"),
        (1, "auto_approve"),
    ],
)
def test_threshold_boundaries(score, expected):
    assert route_for(score) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/a/b/pull/1",
        "https://github.com.evil/a/b/pull/1",
        "https://example.com/github.com/a/b/pull/1",
        "https://github.com/a/b/issues/1",
        "https://github.com/a/b/pull/0",
        "https://github.com/a/b/pull/1?x=1",
    ],
)
def test_invalid_urls(value):
    with pytest.raises(ValueError):
        validate_pr_url(value)


class CountingBackend(DemoBackend):
    def __init__(self):
        self.fetches = 0
        self.analyses = 0
        self.posts = []

    def fetch(self, value):
        self.fetches += 1
        return super().fetch(value)

    def analyze(self, state, *, refine=False):
        self.analyses += 1
        return super().analyze(state, refine=refine)

    def post(self, pr_url, body):
        self.posts.append((pr_url, body))


async def test_durable_resume_approval_and_audit_once():
    backend = CountingBackend()
    result = await run_session(url(), "durable", backend=backend)
    assert result["interrupt_payload"]["kind"] == "approval_request"
    loaded = await load_session("durable")
    assert loaded["interrupt_payload"] == result["interrupt_payload"]
    # Each call closes/reopens the database and compiles a fresh graph.
    again = await run_session(url(), "durable", backend=backend)
    assert again["interrupt_payload"] == result["interrupt_payload"]
    result = await run_session(url(), "durable", {"choice": "approve"}, backend=backend)
    assert result["final_action"] == "previewed"
    assert backend.fetches == backend.analyses == 1
    assert backend.posts == []
    await run_session(url(), "durable", {"choice": "approve"}, backend=backend)
    assert backend.analyses == 1
    events = await replay_events("durable")
    assert [e["action"] for e in events] == [
        "fetch_pr",
        "analyze",
        "route",
        "human_approval",
        "human_approval",
        "commit",
    ]
    assert sum(e["decision"] == "pending" and e["action"] == "human_approval" for e in events) == 1
    response = events[-2]
    assert response["reviewer_id"] == "fixture-reviewer"
    assert response["decision"] == "approve"
    assert all(e["execution_time_ms"] >= 0 for e in events)


async def test_rejection_does_not_publish():
    backend = CountingBackend()
    await run_session(url(), "reject", backend=backend)
    result = await run_session(
        url(), "reject", {"choice": "reject", "feedback": "Missing tests"}, backend=backend
    )
    assert result["final_action"] == "rejected"
    assert result["posted_comment_body"] is None
    assert backend.posts == []


async def test_edit_is_confirmed_and_used_in_final_body():
    await run_session(url(), "edit", backend_mode="demo")
    result = await run_session(
        url(), "edit", {"choice": "edit", "feedback": "Ship only after migration tests."}
    )
    assert result["interrupt_payload"]["edited"] is True
    assert result["interrupt_payload"]["summary"] == "Ship only after migration tests."
    assert not result.get("final_action")
    result = await run_session(url(), "edit", {"choice": "approve"})
    assert result["posted_comment_body"] == "Ship only after migration tests."


async def test_escalation_synthesis_requires_final_confirmation():
    backend = CountingBackend()
    result = await run_session(url(2), "qa", backend=backend)
    payload = result["interrupt_payload"]
    assert payload["kind"] == "escalation"
    assert len(payload["questions"]) >= 2
    answers = {
        q: "Use Argon2id, bind SQL parameters and add security regression tests."
        for q in payload["questions"]
    }
    result = await run_session(url(2), "qa", answers, backend=backend)
    assert result["interrupt_payload"]["kind"] == "approval_request"
    assert result["synthesized"] is True
    assert result["analysis"].confidence == 0.55
    assert backend.analyses == 2
    assert backend.posts == []
    result = await run_session(url(2), "qa", {"choice": "reject"}, backend=backend)
    assert result["final_action"] == "rejected"
    events = await replay_events("qa")
    assert sum(e["action"] == "escalate" and e["decision"] == "pending" for e in events) == 1
    synthesis = next(e for e in events if e["action"] == "synthesize")
    assert synthesis["confidence"] == 0.55


async def test_auto_branch_does_not_interrupt_and_no_high_risk_auto_audit():
    result = await run_session(url(3), "auto", backend_mode="demo")
    assert result["final_action"] == "auto_previewed"
    assert "interrupt_payload" not in result
    events = await replay_events("auto")
    assert any(e["action"] == "auto_approve" for e in events)
    assert not any(e["decision"] == "auto" and e["risk_level"] == "high" for e in events)


async def test_invalid_human_reply_keeps_session_pending():
    result = await run_session(url(), "invalid", backend_mode="demo")
    for reply in [
        {"choice": "yes"},
        {"choice": "edit", "feedback": " "},
        {"choice": "approve", "feedback": 3},
    ]:
        with pytest.raises(ValueError):
            await run_session(url(), "invalid", reply)
    assert (await load_session("invalid"))["interrupt_payload"] == result["interrupt_payload"]


async def test_incomplete_escalation_answers_are_rejected():
    await run_session(url(2), "empty", backend_mode="demo")
    with pytest.raises(ValueError):
        await run_session(url(2), "empty", {})
    assert (await load_session("empty"))["interrupt_payload"]["kind"] == "escalation"


async def test_wrong_pr_cannot_resume_session():
    await run_session(url(), "owner", backend_mode="demo")
    with pytest.raises(ValueError, match="another PR"):
        await run_session(url(2), "owner", {"choice": "approve"})


async def test_publication_success_and_failure_are_recorded(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    backend = CountingBackend()
    await run_session(url(), "publish", backend=backend, publish_mode="live")
    result = await run_session(url(), "publish", {"choice": "approve"}, backend=backend)
    assert result["final_action"] == "committed"
    assert len(backend.posts) == 1
    assert "<!-- day27-review:" in backend.posts[0][1]
    await run_session(url(), "publish", {"choice": "approve"}, backend=backend)
    assert len(backend.posts) == 1

    def fail(*args):
        raise RuntimeError("sensitive-server-error-not-for-audit")

    backend.post = fail
    await run_session(url(), "failure", backend=backend, publish_mode="live")
    result = await run_session(url(), "failure", {"choice": "approve"}, backend=backend)
    assert result["final_action"] == "commit_failed"
    assert "sensitive" not in str(await replay_events("failure"))
    assert (await replay_events("failure"))[-1]["decision"] == "failed"


def test_provider_exception_text_not_shown_as_success():
    demo_state = {
        "pr_url": url(),
        "analysis": DemoBackend().analyze({"pr_diff": "typo"}),
        "backend_mode": "demo",
        "publish_mode": "live",
    }
    assert publish_review(demo_state)["final_action"] == "previewed"


def test_synthesis_prompt_retains_diff_initial_review_and_answers():
    analysis = DemoBackend().analyze({"pr_diff": "hashlib.md5"})
    messages = analysis_messages(
        {
            "pr_title": "Auth",
            "pr_diff": "hashlib.md5",
            "analysis": analysis,
            "escalation_answers": {"Why?": "Legacy"},
        },
        refine=True,
    )
    assert "hashlib.md5" in messages[1]["content"]
    assert "initial_analysis" in messages[1]["content"]
    assert "Legacy" in messages[1]["content"]


def patch_early_exercises(monkeypatch):
    backend = DemoBackend()

    class FakeLLM:
        def with_structured_output(self, schema):
            assert schema is PRAnalysis
            return self

        def invoke(self, messages):
            text = messages[-1]["content"]
            return backend.analyze({"pr_diff": text}, refine="reviewer_answers" in text)

    monkeypatch.setattr(ex1, "fetch_pr", backend.fetch)
    monkeypatch.setattr(ex1, "get_llm", FakeLLM)
    monkeypatch.setattr(ex3, "get_llm", FakeLLM)


@pytest.mark.parametrize(
    "number,decision", [(1, "human_approval"), (2, "escalate"), (3, "auto_approve")]
)
def test_exercise1_real_graph_routes_all_paths(monkeypatch, number, decision):
    patch_early_exercises(monkeypatch)
    result = ex1.build_graph().invoke({"pr_url": url(number)})
    assert result["decision"] == decision


def test_exercise2_interrupt_resume_with_memory_saver(monkeypatch):
    patch_early_exercises(monkeypatch)
    graph = ex2.build_graph()
    cfg = {"configurable": {"thread_id": "memory"}}
    result = graph.invoke({"pr_url": url(), "publish_mode": "preview"}, cfg)
    assert result["__interrupt__"][0].value["kind"] == "approval_request"
    result = graph.invoke(Command(resume={"choice": "reject"}), cfg)
    assert result["final_action"] == "rejected"


@pytest.mark.parametrize("choice", ["reject", "edit"])
def test_exercise2_nonapproval_skips_publication_even_without_feedback(monkeypatch, choice):
    patch_early_exercises(monkeypatch)
    posted = []
    monkeypatch.setattr(ex2, "publish_review", lambda state: posted.append(state))
    graph = ex2.build_graph()
    cfg = {"configurable": {"thread_id": choice}}
    result = graph.invoke({"pr_url": url(), "publish_mode": "live"}, cfg)
    assert not posted
    result = graph.invoke(Command(resume={"choice": choice, "feedback": ""}), cfg)
    assert result["final_action"] == "rejected"
    assert not result.get("__interrupt__")
    assert not posted


def test_exercise2_payload_and_approve_publish_after_interrupt_only(monkeypatch):
    patch_early_exercises(monkeypatch)
    original_fetch = ex1.fetch_pr

    def long_diff(value):
        pr = original_fetch(value)
        pr.diff += "\n+test change" * 300
        return pr

    monkeypatch.setattr(ex1, "fetch_pr", long_diff)
    posts = []

    def publish(state):
        posts.append(dict(state))
        return {"final_action": "committed"}

    monkeypatch.setattr(ex2, "publish_review", publish)
    graph = ex2.build_graph()
    cfg = {"configurable": {"thread_id": "approve-memory"}}
    result = graph.invoke({"pr_url": url(), "publish_mode": "live"}, cfg)
    assert not posts
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "approval_request"
    assert payload["confidence"] == result["analysis"].confidence
    assert payload["confidence_reasoning"] == result["analysis"].confidence_reasoning
    assert payload["summary"] == result["analysis"].summary
    assert payload["comments"] == [c.model_dump() for c in result["analysis"].comments]
    assert payload["diff_preview"] == result["pr_diff"][:2000]
    assert len(payload["diff_preview"]) == 2000
    result = graph.invoke(Command(resume={"choice": "approve", "feedback": "Reviewed"}), cfg)
    assert result["final_action"] == "committed"
    assert len(posts) == 1
    assert posts[0]["human_feedback"] == "Reviewed"
    assert not graph.get_state(cfg).next


@pytest.mark.parametrize("mode", ["live", "preview"])
def test_exercise3_refines_then_commits_without_second_interrupt(monkeypatch, mode):
    patch_early_exercises(monkeypatch)
    posts = []

    def publication(state):
        posts.append(dict(state))
        return {
            "final_action": "committed" if mode == "live" else "previewed",
            "posted_comment_body": render_comment_body(state),
        }

    monkeypatch.setattr(ex3, "publish_review", publication)
    graph = ex3.build_graph()
    cfg = {"configurable": {"thread_id": "qa-memory"}}
    result = graph.invoke({"pr_url": url(2), "publish_mode": mode}, cfg)
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "escalation"
    assert payload["pr_url"] == url(2)
    assert payload["confidence"] == result["analysis"].confidence
    assert payload["confidence_reasoning"] == result["analysis"].confidence_reasoning
    assert payload["summary"] == result["analysis"].summary
    assert payload["risk_factors"] == result["analysis"].risk_factors
    assert payload["questions"] == result["analysis"].escalation_questions
    assert 2 <= len(payload["questions"]) <= 4
    assert not posts
    answers = {
        q: "Security policy applies; the code has not been fixed." for q in payload["questions"]
    }
    result = graph.invoke(Command(resume=answers), cfg)
    expected = "committed_after_escalation" if mode == "live" else "previewed_after_escalation"
    assert result["final_action"] == expected
    assert result["analysis"].confidence == 0.55  # No forced confidence increase or rerouting.
    assert result["escalation_answers"] == answers
    assert not result.get("__interrupt__")
    assert not graph.get_state(cfg).next
    assert len(posts) == 1
    assert "Reviewer answered escalation questions" in result["posted_comment_body"]
    for question, answer in answers.items():
        assert question in result["posted_comment_body"]
        assert answer in result["posted_comment_body"]


@pytest.mark.parametrize("choice", ["approve", "reject", "edit"])
def test_exercise3_medium_confidence_still_requires_approve(monkeypatch, choice):
    patch_early_exercises(monkeypatch)
    posted = []

    def publish(state):
        posted.append(dict(state))
        return {"final_action": "committed"}

    monkeypatch.setattr(ex3, "publish_review", publish)
    graph = ex3.build_graph()
    cfg = {"configurable": {"thread_id": "medium-" + choice}}
    result = graph.invoke({"pr_url": url(), "publish_mode": "live"}, cfg)
    assert result["__interrupt__"][0].value["kind"] == "approval_request"
    assert not posted
    result = graph.invoke(Command(resume={"choice": choice}), cfg)
    assert result["final_action"] == ("committed" if choice == "approve" else "rejected")
    assert len(posted) == (1 if choice == "approve" else 0)


def test_exercise3_incomplete_answers_do_not_synthesize_or_publish(monkeypatch):
    patch_early_exercises(monkeypatch)
    posted = []
    monkeypatch.setattr(ex3, "publish_review", lambda state: posted.append(state))
    graph = ex3.build_graph()
    cfg = {"configurable": {"thread_id": "missing-answers"}}
    result = graph.invoke({"pr_url": url(2)}, cfg)
    questions = result["__interrupt__"][0].value["questions"]
    with pytest.raises(ValueError, match="Answer every escalation question"):
        graph.invoke(Command(resume={questions[0]: "Only one answer"}), cfg)
    assert not posted
    assert not graph.get_state(cfg).values.get("synthesized")


def test_escalation_fallback_provides_two_questions_without_hiding_missing_llm_output():
    state = {
        "pr_url": url(2),
        "pr_diff": "changed code",
        "pr_files": ["storage.py"],
        "analysis": PRAnalysis(
            summary="Missing context", confidence=0.4, confidence_reasoning="Policy unspecified"
        ),
    }
    assert state["analysis"].escalation_questions == []
    payload = escalation_payload(state)
    assert len(payload["questions"]) == 2
    assert "storage.py" in payload["questions"][0]


def test_streamlit_review_and_reject():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=20
    ).run()
    assert not app.exception
    next(button for button in app.button if button.label == "Run review").click().run()
    assert not app.exception
    assert any("Your review is needed" in heading.value for heading in app.subheader)
    next(button for button in app.button if button.label == "Reject").click().run()
    assert not app.exception
    assert any("Review rejected" in item.value for item in app.warning)
