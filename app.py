"""Exercise 5 — persistent Streamlit approval UI. Run: uv run streamlit run app.py."""

from __future__ import annotations

import asyncio
import json

import streamlit as st

from common.db import replay_events
from exercises.review_support import validate_pr_url
from exercises.runtime import (
    load_environment,
    load_session,
    new_thread,
    recent_sessions,
    run_session,
)

load_environment()
st.set_page_config(
    page_title="Review Desk · Day27", page_icon=":material/rate_review:", layout="wide"
)
st.markdown(
    """<style>
    .block-container {max-width: 1160px; padding-top: 2.6rem; padding-bottom: 4rem;}
    h1 {letter-spacing: -.05em; font-weight: 750;}
    h2,h3 {letter-spacing: -.025em;}
    .eyebrow {font: 600 .72rem ui-monospace, monospace; letter-spacing: .17em; color: #8DABBF;}
    .intro {color:#A9B9CD; max-width:720px; font-size:1.08rem; line-height:1.6;}
    [data-testid="stMetricValue"] {font-size:1.8rem; font-weight:650;}
    [data-testid="stMetricLabel"] {color:#A9B9CD;}
    [data-testid="stVerticalBlockBorderWrapper"] {border-color:#334155;}
    button {min-height:44px;}
    button:focus-visible, input:focus-visible, textarea:focus-visible {outline:2px solid #65D6A3; outline-offset:3px;}
    @media (max-width:640px) {
      .block-container {padding:1.4rem 1rem 3rem;}
      h1 {font-size:2.3rem;}
    }
    @media (prefers-reduced-motion:reduce) {* {animation:none!important; transition:none!important;}}
</style>""",
    unsafe_allow_html=True,
)


def safe_error(error):
    status = getattr(getattr(error, "response", None), "status_code", None)
    label = type(error).__name__ + (f" · HTTP {status}" if status else "")
    st.error(
        f"The request could not finish ({label}). Check your provider settings or resume this session."
    )


def use_result(result):
    st.session_state.result = result
    st.session_state.thread_id = result.get("thread_id", st.session_state.get("thread_id"))
    st.session_state.pr_url = result.get("pr_url", st.session_state.get("pr_url", ""))
    if st.session_state.thread_id:
        st.query_params["thread"] = st.session_state.thread_id


async def run_graph(
    pr_url, thread_id, resume_value=None, *, backend_mode="live", publish_mode="preview"
):
    return await run_session(
        pr_url, thread_id, resume_value, backend_mode=backend_mode, publish_mode=publish_mode
    )


def render_comments(payload):
    if payload.get("risk_factors"):
        st.warning("Review focus: " + "; ".join(payload["risk_factors"]))
    for comment in payload.get("comments", []):
        with st.container(border=True):
            st.caption(
                f"{comment['severity'].upper()} · {comment['file']}:{comment.get('line') or '—'}"
            )
            st.write(comment["body"])
    with st.expander("Inspect the complete diff"):
        st.code(
            payload.get("diff_preview", ""), language="diff", line_numbers=True, wrap_lines=True
        )


def render_approval_card(payload):
    label = "Confirm the refined review" if payload.get("refined") else "Your review is needed"
    if payload.get("edited"):
        label = "Confirm your edited review"
    st.subheader(label)
    st.caption(f"Model confidence {payload['confidence']:.0%} · {payload['confidence_reasoning']}")
    st.write(payload["summary"])
    render_comments(payload)
    round_id = st.session_state.result.get("approval_round", 0)
    key = f"{st.session_state.thread_id}_{round_id}"
    feedback = st.text_area(
        "Reviewer note or replacement review",
        key="feedback_" + key,
        help="For Edit, enter the complete replacement review. You will confirm it before publication.",
    )
    approve, reject, edit = st.columns(3)
    if approve.button("Approve", type="primary", use_container_width=True, key="approve_" + key):
        return {"choice": "approve", "feedback": feedback}
    if reject.button("Reject", use_container_width=True, key="reject_" + key):
        return {"choice": "reject", "feedback": feedback}
    if edit.button("Edit", use_container_width=True, key="edit_" + key):
        if not feedback.strip():
            st.error("Enter replacement review text before choosing Edit.")
            return None
        return {"choice": "edit", "feedback": feedback}
    return None


def render_escalation_card(payload):
    st.subheader("Add context before this review proceeds")
    st.caption(f"Model confidence {payload['confidence']:.0%} · {payload['confidence_reasoning']}")
    st.error("Human context required: " + "; ".join(payload.get("risk_factors", [])))
    st.write(payload["summary"])
    with st.expander("Inspect the complete diff"):
        st.code(payload.get("diff_preview", ""), language="diff", wrap_lines=True)
    with st.form("escalation_" + st.session_state.thread_id):
        answers = {
            q: st.text_area(q, key=f"answer_{st.session_state.thread_id}_{i}")
            for i, q in enumerate(payload["questions"])
        }
        submitted = st.form_submit_button("Refine review with these answers", type="primary")
    if submitted:
        if not all(value.strip() for value in answers.values()):
            st.error("Answer each question so the reviewer context is complete.")
            return None
        return answers
    return None


def render_final(result):
    action = result.get("final_action")
    if action in {"previewed", "auto_previewed"}:
        st.success("Review complete · draft saved")
        st.caption("Preview mode. No comment was posted to GitHub.")
    elif action in {"committed", "auto_committed"}:
        st.success("Review complete · comment posted")
        st.link_button("View review on GitHub", result.get("comment_url") or result["pr_url"])
    elif action == "rejected":
        st.warning("Review rejected · no comment posted")
    elif action == "commit_failed":
        st.error("The comment could not be posted. " + result.get("publish_error", ""))
    if result.get("posted_comment_body"):
        st.markdown(result["posted_comment_body"])
        st.download_button(
            "Download review", result["posted_comment_body"], "pr-review.md", "text/markdown"
        )


def main():
    st.session_state.setdefault("thread_id", None)
    st.session_state.setdefault("pr_url", "")
    st.session_state.setdefault("result", {})
    requested_thread = st.query_params.get("thread")
    if requested_thread and requested_thread != st.session_state.thread_id:
        try:
            restored = asyncio.run(load_session(requested_thread))
            if restored:
                use_result(restored)
            else:
                st.warning("That session could not be found in this database.")
        except Exception as error:
            safe_error(error)

    with st.sidebar:
        st.markdown('<div class="eyebrow">REVIEW DESK / DAY 27</div>', unsafe_allow_html=True)
        st.header("Workspace")
        mode = st.radio(
            "Data source",
            ["Offline demo", "Live GitHub + LLM"],
            index=1 if st.session_state.result.get("backend_mode") == "live" else 0,
        )
        backend_mode = "demo" if mode == "Offline demo" else "live"
        publish = False
        if backend_mode == "demo":
            st.caption("Synthetic PRs. No API key needed; no GitHub writes.")
        else:
            publish = st.checkbox("Publish approved reviews to GitHub", value=False)
            st.caption("" if publish else "Preview only: reviews are saved locally.")
        st.divider()
        st.subheader("Recent sessions")
        for row in asyncio.run(recent_sessions()):
            short = row["thread_id"][:8]
            risk = {1: "low", 2: "medium", 3: "high"}[row["risk"]]
            if st.button(
                f"PR #{row['pr_url'].rsplit('/', 1)[-1]} · {risk} · {short}",
                key="load_" + row["thread_id"],
                use_container_width=True,
                help=row["pr_url"],
            ):
                use_result(asyncio.run(load_session(row["thread_id"])))
                st.rerun()
            st.caption(f"{row['events']} events · {row['last_event'][:16]} UTC")
        if st.button("Start a new session", use_container_width=True):
            st.session_state.thread_id = None
            st.session_state.result = {}
            st.session_state.pr_url = ""
            st.query_params.clear()
            st.rerun()

    st.markdown(
        '<div class="eyebrow">HUMAN-IN-THE-LOOP / PULL REQUEST REVIEW</div>', unsafe_allow_html=True
    )
    st.title("A second set of eyes.\nYour final call.")
    st.markdown(
        '<p class="intro">Read the changes, inspect the reasoning, and give risky work the human attention it needs.</p>',
        unsafe_allow_html=True,
    )
    if backend_mode == "demo":
        st.info("Offline demonstration · synthetic data · no LLM or GitHub calls")
    with st.container(border=True):
        if backend_mode == "demo":
            scenario = st.selectbox(
                "Demo scenario",
                [
                    "1 · Schema change / approval",
                    "2 · Authentication / escalation",
                    "3 · Typo / automatic",
                ],
            )
            default_url = f"https://github.com/demo/shop/pull/{scenario[0]}"
        else:
            default_url = (
                st.session_state.pr_url or "https://github.com/VinUni-AI20k/PR-Demo/pull/1"
            )
        with st.form("start"):
            pr_url = st.text_input(
                "Pull request URL",
                value=default_url,
                placeholder="https://github.com/owner/repo/pull/1",
            )
            submitted = st.form_submit_button("Run review", type="primary")
        if submitted:
            try:
                valid_url = validate_pr_url(pr_url)
                thread = new_thread()
                st.session_state.thread_id = thread
                st.session_state.pr_url = valid_url
                st.session_state.result = {}
                st.query_params["thread"] = thread
                with st.spinner("Reading the diff and preparing the review…"):
                    result = asyncio.run(
                        run_graph(
                            valid_url,
                            thread,
                            backend_mode=backend_mode,
                            publish_mode="live" if publish else "preview",
                        )
                    )
                use_result(result)
                st.rerun()
            except ValueError as error:
                st.error(str(error))
            except Exception as error:
                safe_error(error)

    result = st.session_state.result
    if result:
        if result.get("backend_mode") == "demo":
            st.caption("This saved session uses synthetic demo data.")
        elif result.get("publish_mode") == "live":
            st.warning("This session will publish a GitHub comment after approval.")
        else:
            st.caption("This saved session uses live data with local preview publication.")
        analysis = result.get("analysis")
        if analysis:
            cols = st.columns(3)
            cols[0].metric("Model confidence", f"{analysis.confidence:.0%}")
            cols[1].metric("Review route", result.get("decision", "").replace("_", " ").title())
            cols[2].metric("Files changed", len(result.get("pr_files", [])))
        payload = result.get("interrupt_payload")
        if payload:
            with st.container(border=True):
                answer = (
                    render_approval_card(payload)
                    if payload["kind"] == "approval_request"
                    else render_escalation_card(payload)
                )
                if answer is not None:
                    try:
                        with st.spinner("Applying your decision…"):
                            use_result(
                                asyncio.run(
                                    run_graph(
                                        st.session_state.pr_url, st.session_state.thread_id, answer
                                    )
                                )
                            )
                        st.rerun()
                    except Exception as error:
                        safe_error(error)
        elif result.get("final_action"):
            render_final(result)
        elif st.button("Resume saved work"):
            try:
                use_result(
                    asyncio.run(run_graph(st.session_state.pr_url, st.session_state.thread_id))
                )
                st.rerun()
            except Exception as error:
                safe_error(error)
        with st.expander("Session audit trail"):
            rows = asyncio.run(replay_events(st.session_state.thread_id))
            st.dataframe(rows, hide_index=True, use_container_width=True)
            st.download_button(
                "Download audit JSON",
                json.dumps(rows, indent=2),
                "audit.json",
                "application/json",
            )
        st.caption("Session " + str(st.session_state.thread_id))
    else:
        st.caption(
            "73%+ automatic · 58–72% approval · below 58% escalation. Confidence is self-reported by the model."
        )


if __name__ == "__main__":
    main()
