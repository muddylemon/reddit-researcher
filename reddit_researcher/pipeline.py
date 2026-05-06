from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .config import AnalyzeConfig, ProjectConfig, ScrapeConfig
from .ollama_client import OllamaClient
from .progress import RunLogger
from .prompting import (
    build_chunk_prompt,
    build_corpus,
    build_search_corpus,
    build_synthesis_prompt,
    chunk_text,
    load_prompt_text,
    load_terms,
    quote_search_term,
    scope_label_for,
)
from .reddit_client import RedditClient
from .relevance import RelevanceConfig, review_post_relevance
from .storage import (
    append_jsonl,
    create_run_dir,
    read_jsonl,
    slugify,
    write_json,
    write_jsonl,
    write_text,
)


def scrape_subreddit(
    *,
    subreddit: str,
    output_root: Path,
    scrape: ScrapeConfig,
    relevance: RelevanceConfig | None = None,
) -> Path:
    """Scrape a single subreddit's hot/new/top/rising listing."""
    run_dir = create_run_dir(output_root=output_root, scope=subreddit)
    logger = RunLogger(run_dir)
    client = RedditClient(
        user_agent=scrape.user_agent,
        pause_seconds=scrape.pause_seconds,
        max_retries=scrape.max_retries,
    )

    logger.info(f"Starting subreddit scrape r/{subreddit} into {run_dir}")
    posts, raw_posts = client.fetch_posts(
        subreddit=subreddit,
        sort=scrape.sort,
        limit=scrape.post_limit,
        time_filter=scrape.time_filter,
    )

    all_comments: list[dict] = []
    raw_comment_payloads: dict[str, object] = {}
    relevance_rows: list[dict] = []

    for index, post in enumerate(posts, start=1):
        logger.info(f"Comment fetch {index}/{len(posts)}: {post.id}")
        comments, raw_comments = client.fetch_comments(
            permalink=post.permalink,
            post_id=post.id,
            limit=scrape.comment_limit,
        )
        post.comments = comments
        all_comments.extend(comment.to_dict() for comment in comments)
        raw_comment_payloads[post.id] = raw_comments
        if relevance is not None:
            review = review_post_relevance(post.to_dict(), relevance)
            relevance_rows.append(review)

    write_json(run_dir / "raw" / "posts.json", raw_posts)
    for post_id, payload in raw_comment_payloads.items():
        write_json(run_dir / "raw" / "comments" / f"{post_id}.json", payload)

    write_jsonl(run_dir / "normalized" / "posts.jsonl", (post.to_dict() for post in posts))
    write_jsonl(run_dir / "normalized" / "comments.jsonl", all_comments)

    if relevance_rows:
        write_jsonl(run_dir / "review" / "relevance_review.jsonl", relevance_rows)
        relevant_posts = [
            post.to_dict()
            for post, review in zip(posts, relevance_rows, strict=True)
            if review["decision"] in {"include", "review"}
        ]
        write_jsonl(run_dir / "normalized" / "relevant_posts.jsonl", relevant_posts)

    manifest = {
        "mode": "subreddit",
        "subreddit": subreddit,
        "sort": scrape.sort,
        "time_filter": scrape.time_filter,
        "post_limit": scrape.post_limit,
        "comment_limit": scrape.comment_limit,
        "scraped_at_utc": datetime.now(UTC).isoformat(),
        "post_count": len(posts),
        "comment_count": len(all_comments),
    }
    write_json(run_dir / "manifest.json", manifest)
    logger.info(f"Completed subreddit scrape: {len(posts)} posts, {len(all_comments)} comments")
    return run_dir


def scrape_search_terms(
    *,
    terms_file: Path,
    subreddits_file: Path | None,
    output_root: Path,
    run_dir: Path | None,
    scrape: ScrapeConfig,
    relevance: RelevanceConfig | None = None,
    start_term_index: int = 1,
    term_limit: int | None = None,
) -> Path:
    """Run a per-term Reddit search and fetch matching posts and comments."""
    all_search_terms = load_terms(terms_file)
    if not all_search_terms:
        raise ValueError(f"No search terms found in {terms_file}")
    if start_term_index < 1:
        raise ValueError("start_term_index must be 1 or greater")
    start_offset = start_term_index - 1
    end_offset = None if term_limit is None else start_offset + term_limit
    search_terms = all_search_terms[start_offset:end_offset]
    if not search_terms:
        raise ValueError(f"No search terms selected from {terms_file}")
    subreddits = load_terms(subreddits_file) if subreddits_file else []

    if relevance is not None and subreddits and relevance.allowed_subreddits is None:
        relevance = RelevanceConfig(
            keywords=relevance.keywords,
            allowed_subreddits={s.casefold() for s in subreddits},
            require_exact_term_match=relevance.require_exact_term_match,
        )

    if run_dir is None:
        run_dir = create_run_dir(output_root=output_root, scope="all-reddit-search")
    else:
        (run_dir / "raw" / "comments").mkdir(parents=True, exist_ok=True)
        (run_dir / "normalized").mkdir(parents=True, exist_ok=True)
        (run_dir / "analysis" / "chunks").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "review").mkdir(parents=True, exist_ok=True)
    logger = RunLogger(run_dir)
    client = RedditClient(
        user_agent=scrape.user_agent,
        pause_seconds=scrape.pause_seconds,
        max_retries=scrape.max_retries,
    )

    all_posts: list[dict] = []
    all_comments: list[dict] = []
    raw_search_payloads: dict[str, object] = {}
    search_fetch_errors: list[dict[str, str]] = []
    comment_fetch_errors: list[dict[str, str]] = []
    posts_by_term: list[tuple[str, list]] = []
    manifest = {
        "mode": "search",
        "status": "starting",
        "subreddit": "all-reddit-search",
        "search_terms": search_terms,
        "subreddits": subreddits,
        "exact_phrase_search": scrape.exact_phrase,
        "all_search_term_count": len(all_search_terms),
        "term_start_index": start_term_index,
        "term_limit": term_limit,
        "sort": scrape.sort,
        "time_filter": scrape.time_filter,
        "post_limit_per_term": scrape.post_limit,
        "comment_limit": scrape.comment_limit,
        "pause_seconds": scrape.pause_seconds,
        "max_retries": scrape.max_retries,
        "scraped_at_utc": datetime.now(UTC).isoformat(),
        "post_count": 0,
        "comment_count": 0,
        "search_fetch_error_count": 0,
        "search_fetch_errors": [],
        "comment_fetch_error_count": 0,
        "comment_fetch_errors": [],
    }

    def checkpoint(status: str) -> None:
        manifest["status"] = status
        manifest["updated_at_utc"] = datetime.now(UTC).isoformat()
        manifest["post_count"] = len(all_posts)
        manifest["comment_count"] = len(all_comments)
        manifest["search_fetch_error_count"] = len(search_fetch_errors)
        manifest["search_fetch_errors"] = search_fetch_errors
        manifest["comment_fetch_error_count"] = len(comment_fetch_errors)
        manifest["comment_fetch_errors"] = comment_fetch_errors
        write_json(run_dir / "manifest.json", manifest)

    candidate_posts_path = run_dir / "normalized" / "candidate_posts.jsonl"
    posts_path = run_dir / "normalized" / "posts.jsonl"
    relevant_posts_path = run_dir / "normalized" / "relevant_posts.jsonl"
    comments_path = run_dir / "normalized" / "comments.jsonl"
    review_path = run_dir / "review" / "relevance_review.jsonl"
    for path in (candidate_posts_path, posts_path, relevant_posts_path, comments_path, review_path):
        if not path.exists():
            write_text(path, "")
    checkpoint("starting")
    logger.info(f"Starting Reddit search scrape for {len(search_terms)} terms into {run_dir}")

    existing_candidates = read_jsonl(candidate_posts_path) if candidate_posts_path.stat().st_size > 0 else []
    existing_candidate_terms = {row.get("search_term") for row in existing_candidates}
    processed_post_keys = {
        (row.get("search_term"), row.get("id"))
        for row in read_jsonl(posts_path)
        if row.get("search_term") and row.get("id")
    }

    search_targets = subreddits or [None]
    for index, search_term in enumerate(search_terms, start=1):
        if search_term in existing_candidate_terms:
            term_posts = [row for row in existing_candidates if row.get("search_term") == search_term]
            posts_by_term.append((search_term, term_posts))
            logger.info(f"Reusing {len(term_posts)} candidate posts for {search_term}")
            continue
        query = quote_search_term(search_term) if scrape.exact_phrase else search_term
        term_posts = []
        term_raw_payloads = []
        for subreddit in search_targets:
            target_label = f"r/{subreddit}" if subreddit else "all Reddit"
            logger.info(f"Search {index}/{len(search_terms)} in {target_label}: {query}")
            try:
                posts, raw_posts = client.fetch_search_posts(
                    query=query,
                    sort=scrape.sort,
                    limit=scrape.post_limit,
                    time_filter=scrape.time_filter,
                    subreddit=subreddit,
                )
                logger.info(
                    f"Search {index}/{len(search_terms)} in {target_label} returned {len(posts)} posts for {search_term}"
                )
            except RuntimeError as exc:
                posts = []
                raw_posts = {"query": query, "subreddit": subreddit, "error": str(exc)}
                search_fetch_errors.append(
                    {"search_term": search_term, "subreddit": subreddit or "", "error": str(exc)}
                )
                logger.info(
                    f"Search {index}/{len(search_terms)} in {target_label} failed for {search_term}: {exc}"
                )
            for post in posts:
                post_payload = post.to_dict()
                post_payload["search_term"] = search_term
                term_posts.append(post_payload)
                append_jsonl(candidate_posts_path, post_payload)
            term_raw_payloads.append(raw_posts)
        raw_search_payloads[search_term] = term_raw_payloads
        posts_by_term.append((search_term, term_posts[: scrape.post_limit]))
        write_json(run_dir / "raw" / "posts.json", raw_search_payloads)
        checkpoint("searching")

    total_posts_to_fetch = sum(len(posts) for _, posts in posts_by_term)
    comment_fetch_index = 0
    for search_term, posts in posts_by_term:
        for post in posts:
            post_id = post["id"]
            if (search_term, post_id) in processed_post_keys:
                logger.info(f"Skipping already processed post for {search_term}: {post_id}")
                continue
            comment_fetch_index += 1
            logger.info(
                f"Comment fetch {comment_fetch_index}/{total_posts_to_fetch} for {search_term}: {post_id}"
            )
            try:
                comments, raw_comments = client.fetch_comments(
                    permalink=post["permalink"],
                    post_id=post_id,
                    limit=scrape.comment_limit,
                )
                logger.info(
                    f"Comment fetch {comment_fetch_index}/{total_posts_to_fetch} returned {len(comments)} comments for {post_id}"
                )
            except RuntimeError as exc:
                comments = []
                raw_comments = {"error": str(exc), "permalink": post["permalink"], "post_id": post_id}
                comment_fetch_errors.append(
                    {
                        "search_term": search_term,
                        "post_id": post_id,
                        "permalink": post["permalink"],
                        "error": str(exc),
                    }
                )
                logger.info(
                    f"Comment fetch {comment_fetch_index}/{total_posts_to_fetch} failed for {post_id}: {exc}"
                )
            post_payload = dict(post)
            post_payload["comments"] = [comment.to_dict() for comment in comments]
            all_posts.append(post_payload)
            all_comments.extend(comment.to_dict() for comment in comments)
            review = (
                review_post_relevance(post_payload, relevance)
                if relevance
                else {
                    "post_id": post_id,
                    "search_term": search_term,
                    "subreddit": post.get("subreddit"),
                    "decision": "include",
                    "reason": "no relevance filter configured",
                }
            )
            write_json(
                run_dir / "raw" / "comments" / f"{slugify(f'{search_term}:{post_id}')}.json",
                raw_comments,
            )
            append_jsonl(posts_path, post_payload)
            append_jsonl(review_path, review)
            if review["decision"] in {"include", "review"}:
                append_jsonl(relevant_posts_path, post_payload)
            for comment in comments:
                append_jsonl(comments_path, comment.to_dict())
            processed_post_keys.add((search_term, post_id))
            checkpoint("fetching_comments")

    checkpoint("complete")
    logger.info(
        f"Completed Reddit search scrape: {len(all_posts)} posts, {len(all_comments)} comments, "
        f"{len(search_fetch_errors)} search errors, {len(comment_fetch_errors)} comment errors"
    )
    return run_dir


def extract_from_run(
    *,
    run_dir: Path,
    analyze: AnalyzeConfig,
) -> Path:
    """Run Ollama analysis over an existing run folder.

    Reuses any existing chunk files unless `analyze.force_reextract` is True.
    """
    if analyze.prompt_file is None:
        raise ValueError("analyze.prompt_file must be set to run extraction.")

    relevant_posts_path = run_dir / "normalized" / "relevant_posts.jsonl"
    posts_path = (
        relevant_posts_path
        if relevant_posts_path.exists() and relevant_posts_path.stat().st_size > 0
        else run_dir / "normalized" / "posts.jsonl"
    )
    posts = read_jsonl(posts_path) if posts_path.exists() else []
    comments_path = run_dir / "normalized" / "comments.jsonl"
    comments = read_jsonl(comments_path) if comments_path.exists() else []
    prompt_text = load_prompt_text(analyze.prompt_file)

    manifest_path = run_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    is_search = manifest.get("mode") == "search"
    subreddit = manifest.get("subreddit") or "unknown"
    scope_label = scope_label_for(
        subreddit=None if is_search else subreddit,
        search_terms=manifest.get("search_terms") if is_search else None,
    )
    logger = RunLogger(run_dir, log_name="extract.log")

    if not posts:
        final_path = run_dir / "analysis" / "final.md"
        final_output = "No relevant posts selected for analysis."
        write_text(final_path, final_output)
        logger.info(final_output)
        manifest["analysis"] = {
            "model": analyze.model,
            "prompt_file": str(analyze.prompt_file),
            "ollama_url": analyze.ollama_url,
            "ollama_timeout_seconds": analyze.ollama_timeout_seconds,
            "chunk_char_limit": analyze.chunk_char_limit,
            "chunk_count": 0,
            "total_chunk_count": 0,
            "chunk_limit": analyze.chunk_limit,
            "force_reextract": analyze.force_reextract,
            "analyzed_at_utc": datetime.now(UTC).isoformat(),
            "final_output": str(final_path),
        }
        write_json(manifest_path, manifest)
        return final_path

    corpus = build_search_corpus(posts=posts) if is_search else build_corpus(posts=posts, comments=comments)
    all_chunks = chunk_text(corpus, max_chars=analyze.chunk_char_limit)
    chunks = all_chunks[: analyze.chunk_limit] if analyze.chunk_limit is not None else all_chunks
    logger.info(f"Starting Ollama extraction with {len(chunks)} chunks from {run_dir}")
    client = OllamaClient(base_url=analyze.ollama_url, timeout_seconds=analyze.ollama_timeout_seconds)

    chunk_outputs: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_path = run_dir / "analysis" / "chunks" / f"chunk-{index:03d}.md"
        if not analyze.force_reextract and chunk_path.exists() and chunk_path.stat().st_size > 0:
            logger.info(f"Reusing existing analysis chunk {index}/{len(chunks)}: {chunk_path}")
            chunk_outputs.append(chunk_path.read_text(encoding="utf-8"))
            continue

        logger.info(f"Analysis chunk {index}/{len(chunks)}")
        prompt = build_chunk_prompt(
            scope_label=scope_label,
            prompt_text=prompt_text,
            chunk_text_value=chunk,
            chunk_index=index,
            chunk_count=len(chunks),
        )
        response = client.generate(model=analyze.model, prompt=prompt)
        chunk_outputs.append(response)
        write_text(chunk_path, response)
        logger.info(f"Analysis chunk {index}/{len(chunks)} complete")

    logger.info("Starting final synthesis")
    synthesis_prompt = build_synthesis_prompt(
        scope_label=scope_label,
        prompt_text=prompt_text,
        chunk_outputs=chunk_outputs,
    )
    final_output = client.generate(model=analyze.model, prompt=synthesis_prompt)
    final_path = run_dir / "analysis" / "final.md"
    write_text(final_path, final_output)
    logger.info(f"Final synthesis complete: {final_path}")

    manifest["analysis"] = {
        "model": analyze.model,
        "prompt_file": str(analyze.prompt_file),
        "ollama_url": analyze.ollama_url,
        "ollama_timeout_seconds": analyze.ollama_timeout_seconds,
        "chunk_char_limit": analyze.chunk_char_limit,
        "chunk_count": len(chunks),
        "total_chunk_count": len(all_chunks),
        "chunk_limit": analyze.chunk_limit,
        "force_reextract": analyze.force_reextract,
        "analyzed_at_utc": datetime.now(UTC).isoformat(),
        "final_output": str(final_path),
    }
    write_json(manifest_path, manifest)
    return final_path


def run_project(
    *,
    project: ProjectConfig,
    output_root: Path,
    run_dir: Path | None = None,
    skip_extract: bool = False,
    start_term_index: int = 1,
    term_limit: int | None = None,
) -> Path:
    """Run a project end-to-end: scrape according to mode, then extract."""
    if project.scrape.mode == "subreddit":
        # Subreddit mode does not yet support resuming; --run-dir is honored only by search mode.
        scrape_dir = scrape_subreddit(
            subreddit=project.scrape.subreddit or "",
            output_root=output_root,
            scrape=project.scrape,
            relevance=project.relevance,
        )
    else:
        scrape_dir = scrape_search_terms(
            terms_file=project.scrape.terms_file,  # type: ignore[arg-type]
            subreddits_file=project.scrape.subreddits_file,
            output_root=output_root,
            run_dir=run_dir,
            scrape=project.scrape,
            relevance=project.relevance,
            start_term_index=start_term_index,
            term_limit=term_limit,
        )

    if skip_extract:
        return scrape_dir

    if project.analyze.prompt_file is None:
        return scrape_dir

    extract_from_run(run_dir=scrape_dir, analyze=project.analyze)
    return scrape_dir
