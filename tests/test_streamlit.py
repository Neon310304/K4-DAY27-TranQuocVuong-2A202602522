"""Exercise 5 UI decisions against SQLite and LangGraph; API adapters are fake."""

import asyncio
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from common.db import replay_events
from exercises import runtime
from exercises.review_support import DemoBackend

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HITL_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("GITHUB_USER", "automated-ui-validation")

    class FakeLive(DemoBackend):
        fetches = 0
        analyses = 0

        def fetch(self, url):
            self.fetches += 1
            return super().fetch(url)

        def analyze(self, state, *, refine=False):
            self.analyses += 1
            return super().analyze(state, refine=refine)

    value = FakeLive()
    value.posts = []
    monkeypatch.setattr(runtime, "LiveBackend", lambda: value)
    monkeypatch.setattr(runtime, "post_review_comment", lambda *args: value.posts.append(args))
    monkeypatch.setattr(runtime, "ensure_github_token", lambda: None)
    return value


def button(app, label):
    return next(item for item in app.button if item.label == label)


@pytest.mark.parametrize("number", [1, 2, 3])
def test_browser_controls_reach_publication_only_after_required_decisions(backend, number):
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.radio[0].set_value("Live GitHub + LLM").run()
    app.checkbox[0].check().run()
    pr_url = f"https://github.com/demo/shop/pull/{number}"
    next(item for item in app.text_input if item.label == "Pull request URL").set_value(pr_url)
    button(app, "Run review").click().run()
    assert not app.exception
    thread = app.session_state.thread_id
    assert backend.fetches == 1 and backend.analyses == 1

    if number != 3:
        assert not backend.posts
        if number == 2:
            payload = app.session_state.result["interrupt_payload"]
            for question in payload["questions"]:
                next(item for item in app.text_area if item.label == question).set_value(
                    "Synthetic UI test: require secure defaults; implementation remains unfixed."
                )
            button(app, "Refine review with these answers").click().run()
            assert not app.exception
            assert backend.analyses == 2
            assert not backend.posts
            assert app.session_state.result["interrupt_payload"]["refined"]
        button(app, "Approve").click().run()

    assert not app.exception
    result = app.session_state.result
    assert result["final_action"] == ("auto_committed" if number == 3 else "committed")
    assert result["thread_id"] == thread
    assert len(backend.posts) == 1
    assert backend.posts[0][0] == pr_url
    assert any("comment posted" in item.value for item in app.success)
    links = app.get("link_button")
    assert any(item.proto.url == pr_url for item in links)
    assert any("audit.replay --thread " + thread in item.value for item in app.code)
    if number == 3:
        assert any(item.value == "Automatic review" for item in app.subheader)
        assert any(result["analysis"].summary in item.value for item in app.markdown)
        assert not any(item.label == "Approve" for item in app.button)
    if number == 2:
        assert "Reviewer answered escalation questions" in backend.posts[0][1]

    # A rerun with a completed checkpoint cannot publish the same review again.
    app.run()
    assert not app.exception
    assert len(backend.posts) == 1
    events = asyncio.run(replay_events(thread))
    assert events[-1]["action"] == "commit"
    assert events[-1]["decision"] == ("auto" if number == 3 else "approve")
    assert events[-1]["reviewer_id"] == (None if number == 3 else "automated-ui-validation")


def test_recent_session_restores_original_pr_without_another_analysis(backend):
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.radio[0].set_value("Live GitHub + LLM").run()
    button(app, "Run review").click().run()
    thread = app.session_state.thread_id
    pr_url = app.session_state.pr_url
    rows = asyncio.run(runtime.recent_sessions())
    assert rows[0]["thread_id"] == thread
    assert rows[0]["pr_url"] == pr_url
    assert rows[0]["worst_risk"] == "med"
    assert rows[0]["last_event"]

    button(app, "Start a new session").click().run()
    button(app, next(item.label for item in app.button if thread[:8] in item.label)).click().run()
    assert not app.exception
    assert app.session_state.thread_id == thread
    assert app.session_state.pr_url == pr_url
    assert app.query_params["thread"] == thread
    assert backend.fetches == backend.analyses == 1
    assert not backend.posts
    assert any(pr_url in item.value for item in app.markdown)

    # Reload in a new Streamlit session using only the bookmarked URL.
    fresh = AppTest.from_file(APP, default_timeout=20)
    fresh.query_params["thread"] = thread
    fresh.run()
    assert not fresh.exception
    assert fresh.session_state.result["interrupt_payload"]["kind"] == "approval_request"
    assert backend.fetches == backend.analyses == 1
    button(fresh, "Reject").click().run()
    assert not fresh.exception
    assert not backend.posts
    assert fresh.session_state.result["final_action"] == "rejected"
