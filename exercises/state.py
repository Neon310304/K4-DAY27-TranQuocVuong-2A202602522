"""Extra runtime fields without changing the provided ReviewState contract."""

from common.schemas import ReviewState


class RuntimeState(ReviewState, total=False):
    backend_mode: str
    publish_mode: str
    reviewer_id: str | None
    comment_url: str | None
    publish_error: str | None
    edited_review: str | None
    approval_round: int
    synthesized: bool
