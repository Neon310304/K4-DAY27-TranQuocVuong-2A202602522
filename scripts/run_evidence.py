"""Record real graph executions. Offline fixtures and live-provider runs stay separate.

Live mode fetches/analyzes the two public PRs and stops at HITL; it never sends
review comments or invents a human approval. Re-running creates new sessions.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from common.db import replay_events
from exercises.runtime import load_environment, new_thread, run_session

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    paths = [
        ROOT / "app.py",
        ROOT / "pyproject.toml",
        *sorted((ROOT / "exercises").glob("*.py")),
        *sorted((ROOT / "common").glob("*.py")),
        *sorted((ROOT / "audit").glob("*.py")),
        ROOT / "audit/schema.sql",
    ]
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def export_state(state):
    value = dict(state)
    if "analysis" in value:
        value["analysis"] = value["analysis"].model_dump(mode="json")
    return value


async def collect(live=False):
    load_environment()
    evidence_dir = ROOT / "reports/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HITL_DB_PATH"] = str(ROOT / ("live_evidence.db" if live else "demo_evidence.db"))
    runs = []
    scenarios = [1, 2] if live else [1, 2, 3]
    for number in scenarios:
        url = (
            f"https://github.com/VinUni-AI20k/PR-Demo/pull/{number}"
            if live
            else f"https://github.com/demo/shop/pull/{number}"
        )
        thread_id = new_thread()
        result = await run_session(url, thread_id, backend_mode="live" if live else "demo")
        snapshots = [export_state(result)]
        if not live:
            # These are explicitly synthetic validation responses, never attributed
            # to the student as a real human approval of a live PR.
            os.environ["GITHUB_USER"] = "automated-offline-validation"
            while result.get("interrupt_payload"):
                payload = result["interrupt_payload"]
                response = (
                    {
                        q: "Synthetic validation: require secure defaults and regression tests."
                        for q in payload["questions"]
                    }
                    if payload["kind"] == "escalation"
                    else {"choice": "approve", "feedback": "Synthetic fixture approval only"}
                )
                result = await run_session(url, thread_id, response)
                snapshots.append(export_state(result))
        events = await replay_events(thread_id)
        runs.append(
            {"thread_id": thread_id, "pr_url": url, "snapshots": snapshots, "audit_events": events}
        )
        print(
            f"{thread_id} PR#{number}: {result.get('decision')}; "
            f"confidence={result['analysis'].confidence:.2f}; "
            f"status={result.get('final_action') or 'awaiting_reviewer'}",
            flush=True,
        )
    result = {
        "format_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "live_provider_read_only" if live else "offline_synthetic",
        "python_version": platform.python_version(),
        "llm_model_requested": os.getenv("LLM_MODEL") if live else None,
        "llm_base_url": os.getenv("LLM_BASE_URL") if live else None,
        "github_comments_posted": 0,
        "human_decisions": "none; sessions remain pending" if live else "synthetic test responses",
        "source_hashes": source_hashes(),
        "runs": runs,
    }
    destination = evidence_dir / ("live_runs.json" if live else "offline_runs.json")
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Saved", destination.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(collect(args.live))
    except Exception as error:
        # Never dump HTTP exceptions that can contain credentials/request data.
        status = getattr(getattr(error, "response", None), "status_code", None)
        print(f"Evidence run failed: {type(error).__name__}; HTTP={status}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
