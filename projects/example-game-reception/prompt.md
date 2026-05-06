For each game in the search terms, build a short reception report grounded in the supplied
Reddit posts and comments.

For each game, output a Markdown section with these sub-headings:

1. **Headline** — one sentence summarizing the overall Reddit sentiment (e.g. "loved on launch
   but now widely seen as bloated", "redeemed by post-launch patches", "polarizing").
2. **What players praise** — 2–4 bullets of recurring praise themes. Cite post or comment ids.
3. **What players criticize** — 2–4 bullets of recurring complaints. Cite ids.
4. **Buy / wait / skip** — what is the community telling potential buyers right now?
5. **Notable shifts** — has sentiment changed over time? (Patch reception, DLC, post-launch
   redemption, etc.) Skip if the data does not support a claim.

Rules of evidence:

- A single hot take is not a pattern. Only call something a recurring theme if multiple
  independent posts/comments support it.
- Distinguish opinion from fact. "People say performance is rough" is OK; "performance is rough"
  without a citation is not.
- If the data is dominated by hype, ads, or off-topic name-drops for a given title, say so plainly
  and keep that game's section short.

Cost-control rule:

- If a chunk has no meaningful discussion of any of the named games (e.g. it's mostly
  unrelated subreddit chatter or low-content posts), write one sentence beginning
  `Not relevant:` and stop.

Use only the supplied Reddit content. Do not pull in outside review-aggregate scores.
