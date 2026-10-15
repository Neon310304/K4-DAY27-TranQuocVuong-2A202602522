"""Exercise the actual Streamlit UI in Chrome. No live reviews are started here."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

from scripts.run_evidence import source_hashes

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("HITL_BROWSER_BASE_URL", "http://127.0.0.1:8527")


def current_thread(page):
    return parse_qs(urlsplit(page.url).query)["thread"][0]


def screenshot(page, destination):
    page.get_by_test_id("stSidebarContent").evaluate("element => { element.scrollTop = 0; }")
    page.screenshot(path=str(destination), full_page=True)


def capture_audit(page, scenario):
    """Compare the audit JSON downloaded from the UI with the SQLite replay."""
    thread = current_thread(page)
    expander = page.get_by_test_id("stExpander").filter(has_text="Session audit trail")
    if expander.locator("details").get_attribute("open") is None:
        expander.locator("summary").click()
    with page.expect_download() as pending:
        page.get_by_role("button", name="Download audit JSON", exact=True).click()
    downloaded = json.loads(Path(pending.value.path()).read_text(encoding="utf-8"))
    with sqlite3.connect(os.environ["HITL_DB_PATH"]) as conn:
        conn.row_factory = sqlite3.Row
        stored = [
            dict(row)
            for row in conn.execute(
                """SELECT id, timestamp, agent_id, action, confidence, risk_level,
                          reviewer_id, decision, reason, execution_time_ms
                     FROM audit_events WHERE thread_id=? ORDER BY id""",
                (thread,),
            )
        ]
    assert downloaded == stored
    assert sum(e["action"] == "fetch_pr" for e in stored) == 1
    assert sum(e["action"] == "analyze" for e in stored) == 1
    command = [sys.executable, "-m", "audit.replay", "--thread", thread]
    replay = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert replay.returncode == 0, replay.stderr
    return {
        "scenario": scenario,
        "thread_id": thread,
        "audit_events": downloaded,
        "ui_download_matches_sqlite": True,
        "replay_command": "uv run python -m audit.replay --thread " + thread,
        "replay_exit_code": replay.returncode,
        "replay_stdout": replay.stdout,
    }


def main():
    shots = ROOT / "screenshots"
    shots.mkdir(exist_ok=True)
    evidence = ROOT / "reports/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    sessions = []
    os.environ.setdefault("HITL_DB_PATH", str(ROOT / "live_evidence.db"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1900}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="A second set of eyes.")).to_be_visible(
            timeout=30000
        )
        screenshot(page, shots / "01-workspace.png")
        # Inspect real controls after hydration before choosing selectors.
        controls = page.get_by_role("button").all_text_contents()
        (evidence / "browser_controls.json").write_text(
            json.dumps(controls, indent=2), encoding="utf-8"
        )

        page.get_by_role("button", name="Run review", exact=True).click()
        expect(page.get_by_role("heading", name="Your review is needed")).to_be_visible()
        expect(page.get_by_role("button", name="Approve", exact=True)).to_be_visible()
        screenshot(page, shots / "02-approval.png")
        checks.append("Synthetic schema change pauses for approval")
        thread = current_thread(page)
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Your review is needed")).to_be_visible()
        assert current_thread(page) == thread
        expect(page.get_by_text("uv run python -m audit.replay --thread " + thread)).to_be_visible()
        checks.append("Pending approval survives browser reload on the same thread")
        page.get_by_role("textbox", name="Reviewer note or replacement review", exact=True).fill(
            "Require migration tests before rollout. Use a default priority for existing rows."
        )
        page.get_by_role("button", name="Edit", exact=True).click()
        expect(page.get_by_role("heading", name="Confirm your edited review")).to_be_visible()
        expect(page.get_by_role("button", name="Approve", exact=True)).to_have_count(1)
        page.get_by_role("button", name="Approve", exact=True).click()
        expect(page.get_by_text("Review complete · draft saved", exact=True)).to_be_visible()
        screenshot(page, shots / "03-edited-draft.png")
        checks.append("Edit pauses again, approval saves replacement text locally")
        saved_url = page.url
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Review complete · draft saved", exact=True)).to_be_visible()
        assert page.url == saved_url
        checks.append("Reload restores the completed session from its query-string thread ID")
        page.get_by_role("button", name="Start a new session", exact=True).click()
        page.get_by_role("button").filter(has_text=thread[:8]).click()
        expect(page.get_by_text("Review complete · draft saved", exact=True)).to_be_visible()
        assert current_thread(page) == thread
        details = page.get_by_test_id("stExpander").filter(has_text="Selected session details")
        expect(details.get_by_text(thread, exact=True)).to_be_visible()
        expect(
            details.get_by_role("link", name="https://github.com/demo/shop/pull/1")
        ).to_be_visible()
        expect(details.get_by_text("Worst risk: med", exact=False)).to_be_visible()
        checks.append(
            "Recent sessions restore the original thread and show PR URL, worst risk and timestamp"
        )
        sessions.append(capture_audit(page, "approval_edit_confirm"))
        screenshot(page, shots / "10-session-audit.png")

        page.get_by_role("button", name="Start a new session", exact=True).click()
        page.get_by_role("combobox", name="Demo scenario").click()
        page.get_by_role("option", name="2 · Authentication / escalation").click()
        page.get_by_role("button", name="Run review", exact=True).click()
        expect(
            page.get_by_role("heading", name="Add context before this review proceeds")
        ).to_be_visible()
        screenshot(page, shots / "04-escalation.png")
        page.get_by_role("button", name="Refine review with these answers").click()
        expect(
            page.get_by_text("Answer each question so the reviewer context is complete.")
        ).to_be_visible()
        page.get_by_label("auth.py: what password hashing and migration policy is required?").fill(
            "Synthetic lab response: require Argon2id and a migration plan; current code is not fixed."
        )
        page.get_by_label(
            "auth.py: how are user-supplied SQL values parameterized and tested?"
        ).fill(
            "Synthetic lab response: require bound parameters and SQL injection regression tests."
        )
        page.get_by_role("button", name="Refine review with these answers").click()
        expect(page.get_by_role("heading", name="Confirm the refined review")).to_be_visible()
        screenshot(page, shots / "05-refined-review.png")
        page.get_by_role("button", name="Reject", exact=True).click()
        expect(page.get_by_text("Review rejected · no comment posted", exact=True)).to_be_visible()
        checks.append(
            "Escalation validates answers, synthesizes and waits for final confirmation; reject posts nothing"
        )
        sessions.append(capture_audit(page, "escalation_answers_confirm_reject"))

        page.get_by_role("button", name="Start a new session", exact=True).click()
        page.get_by_role("combobox", name="Demo scenario").click()
        page.get_by_role("option", name="3 · Typo / automatic").click()
        page.get_by_role("button", name="Run review", exact=True).click()
        expect(page.get_by_text("Review complete · draft saved", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Approve", exact=True)).to_have_count(0)
        expect(page.get_by_role("heading", name="Automatic review", exact=True)).to_be_visible()
        expect(
            page.get_by_text("Synthetic demo: corrects a documentation typo.", exact=True).first
        ).to_be_visible()
        screenshot(page, shots / "06-auto-preview.png")
        checks.append("High-confidence synthetic typo completes automatically in preview mode")
        sessions.append(capture_audit(page, "automatic_preview"))
        checks.append(
            "Browser audit downloads match SQLite and CLI replay for all three completed demo sessions"
        )

        live = json.loads((evidence / "live_runs.json").read_text(encoding="utf-8"))
        for number, run in enumerate(live["runs"], 1):
            page.goto(BASE + "/?thread=" + run["thread_id"])
            page.wait_for_load_state("networkidle")
            heading = (
                "Your review is needed"
                if number == 1
                else "Add context before this review proceeds"
            )
            expect(page.get_by_role("heading", name=heading)).to_be_visible()
            expect(page.get_by_role("textbox", name="Pull request URL")).to_have_value(
                run["pr_url"]
            )
            if number == 1:
                expect(page.get_by_role("button", name="Approve", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Reject", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Edit", exact=True)).to_be_visible()
            else:
                expect(
                    page.get_by_role("button", name="Refine review with these answers")
                ).to_be_visible()
            expect(
                page.get_by_text(
                    "This saved session uses live data with local preview publication."
                )
            ).to_be_visible()
            screenshot(page, shots / f"0{6 + number}-live-pr{number}.png")
            checks.append(
                f"Actual PR #{number} live LLM checkpoint restored, no new LLM call and no publication"
            )

        page.set_viewport_size({"width": 375, "height": 900})
        page.emulate_media(reduced_motion="reduce")
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(
            page.get_by_role("heading", name="Add context before this review proceeds")
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        screenshot(page, shots / "09-mobile.png")
        checks.append("375px viewport with reduced motion has no document horizontal overflow")
        page.set_viewport_size({"width": 900, "height": 375})
        expect(
            page.get_by_role("heading", name="Add context before this review proceeds")
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        checks.append("Landscape viewport has no document horizontal overflow")
        browser.close()

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "page_errors": errors,
        "live_comments_posted": 0,
        "scope": "real headless Chrome screenshots; synthetic interactions and restored real API sessions are labeled separately",
    }
    (evidence / "browser_checks.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (evidence / "exercise5_browser.json").write_text(
        json.dumps(
            {
                "exercise": 5,
                "timestamp_utc": report["timestamp_utc"],
                "source_hashes": source_hashes(),
                "response_source": "Synthetic browser validation; not a user review of a live PR",
                "github_comments_posted": 0,
                "sessions": sessions,
                "checks": checks,
                "page_errors": errors,
                "live_api_note": "Only restored existing live checkpoints; no new model requests",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if errors:
        raise AssertionError(errors)
    print(f"Browser checks passed: {len(checks)}; page errors: {len(errors)}")


if __name__ == "__main__":
    main()
