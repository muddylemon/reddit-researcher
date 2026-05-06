from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class CommentRecord:
    id: str
    post_id: str
    parent_id: str | None
    author: str | None
    body: str
    score: int
    created_utc: float | None
    permalink: str
    depth: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PostRecord:
    id: str
    subreddit: str
    title: str
    author: str | None
    selftext: str
    url: str
    permalink: str
    score: int
    upvote_ratio: float | None
    num_comments: int
    created_utc: float | None
    over_18: bool
    is_self: bool
    link_flair_text: str | None
    sort: str
    time_filter: str | None
    comments: list[CommentRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["comments"] = [comment.to_dict() for comment in self.comments]
        return payload
