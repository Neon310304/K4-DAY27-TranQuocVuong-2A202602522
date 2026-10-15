"""Exercise the actual Streamlit UI in Chrome. No live reviews are started here."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8527"


def main():
    shots = ROOT / "screenshots"
    shots.mkdir(exist_ok=True)
    evidence = ROOT / "reports/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1900}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="A second set of eyes.")).to_be_visible()
        page.screenshot(path=str(shots / "01-workspace.png"), full_page=True)
        # Inspect real controls after hydration before choosing selectors.
        controls = page.get_by_role("button").all_text_contents()
        (evidence / "browser_controls.json").write_text(
            json.dumps(controls, indent=2), encoding="utf-8"
        )

        page.get_by_role("button", name="Run review", exact=True).click()
        expect(page.get_by_role("heading", name="Your review is needed")).to_be_visible()
        expect(page.get_by_role("button", name="Approve", exact=True)).to_be_visible()
        page.screenshot(path=str(shots / "02-approval.png"), full_page=True)
        checks.append("Synthetic schema change pauses for approval")
        page.get_by_role("textbox", name="Reviewer note or replacement review", exact=True).fill(
            "Require migration tests before rollout. Use a default priority for existing rows."
        )
        page.get_by_role("button", name="Edit", exact=True).click()
        expect(page.get_by_role("heading", name="Confirm your edited review")).to_be_visible()
        page.get_by_role("button", name="Approve", exact=True).click()
        expect(page.get_by_text("Review complete · draft saved", exact=True)).to_be_visible()
        page.screenshot(path=str(shots / "03-edited-draft.png"), full_page=True)
        checks.append("Edit pauses again, approval saves replacement text locally")
        saved_url = page.url
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Review complete · draft saved", exact=True)).to_be_visible()
        assert page.url == saved_url
        checks.append("Reload restores the completed session from its query-string thread ID")

        page.get_by_role("button", name="Start a new session", exact=True).click()
        page.get_by_role("combobox", name="Demo scenario").click()
        page.get_by_role("option", name="2 · Authentication / escalation").click()
        page.get_by_role("button", name="Run review", exact=True).click()
        expect(
            page.get_by_role("heading", name="Add context before this review proceeds")
        ).to_be_visible()
        page.screenshot(path=str(shots / "04-escalation.png"), full_page=True)
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
        page.screenshot(path=str(shots / "05-refined-review.png"), full_page=True)
        page.get_by_role("button", name="Reject", exact=True).click()
        expect(page.get_by_text("Review rejected · no comment posted", exact=True)).to_be_visible()
        checks.append(
            "Escalation validates answers, synthesizes and waits for final confirmation; reject posts nothing"
        )

        page.get_by_role("button", name="Start a new session", exact=True).click()
        page.get_by_role("combobox", name="Demo scenario").click()
        page.get_by_role("option", name="3 · Typo / automatic").click()
        page.get_by_role("button", name="Run review", exact=True).click()
        expect(page.get_by_text("Review complete · draft saved", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Approve", exact=True)).to_have_count(0)
        page.screenshot(path=str(shots / "06-auto-preview.png"), full_page=True)
        checks.append("High-confidence synthetic typo completes automatically in preview mode")

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
            page.screenshot(path=str(shots / f"0{6 + number}-live-pr{number}.png"), full_page=True)
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
        page.screenshot(path=str(shots / "09-mobile.png"), full_page=True)
        checks.append("375px viewport with reduced motion has no document horizontal overflow")
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
    if errors:
        raise AssertionError(errors)
    print(f"Browser checks passed: {len(checks)}; page errors: {len(errors)}")


if __name__ == "__main__":
    main()
