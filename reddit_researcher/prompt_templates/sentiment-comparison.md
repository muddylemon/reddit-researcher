# Compare Reddit sentiment across multiple search terms (search mode).

For each search term, build a short reception report grounded in the supplied Reddit posts
and comments.

For each term, output a Markdown section with these sub-headings:

1. **Headline** — one sentence summarizing the overall Reddit sentiment.
2. **What people praise** — 2–4 bullets of recurring praise themes. Cite post or comment ids.
3. **What people criticize** — 2–4 bullets of recurring complaints. Cite ids.
4. **Verdict** — what is the community telling outside observers right now? One or two sentences.
5. **Notable shifts** — has sentiment changed over time? Skip if the data does not support a claim.

Rules of evidence:

- A single hot take is not a pattern. Only call something a recurring theme if multiple
  independent posts or comments support it.
- Distinguish opinion from fact. "People say X is rough" is OK; "X is rough" without a
  citation is not.
- If the data is dominated by ads, hype, or off-topic name-drops for a given term, say so
  plainly and keep that term's section short.

Cost-control rule:

- If a chunk has no meaningful discussion of any of the named terms, write one sentence
  beginning `Not relevant:` and stop.

Use only the supplied Reddit content. Do not pull in outside reviews or scores.
