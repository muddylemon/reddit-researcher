For each tool or framework in the search terms, produce a developer-focused sentiment report
grounded in the supplied Reddit posts and comments.

For each tool, output a Markdown section with these sub-headings:

1. **Who's it for** — one sentence on the audience the community thinks this tool fits.
2. **What works** — 2–4 bullets of recurring praise (DX, performance, ecosystem, etc.).
   Cite post or comment ids.
3. **What hurts** — 2–4 bullets of recurring complaints, gotchas, or production pain.
   Cite ids.
4. **Migration patterns** — what are people switching from, or to, and why? Skip this section
   if the data does not actually contain migration stories.
5. **Verdict** — what does the community currently recommend? Adoption, wait-and-see,
   "use only if X", etc. One or two sentences.

Rules of evidence:

- A single anecdote is not a pattern. Only call something a recurring theme if multiple
  independent posts or comments support it.
- Distinguish "the docs say X" from "I tried it in production and X". Production stories
  are higher-signal; weight them accordingly.
- Common-name collisions are real. If a chunk's mention of "Bun" or "Astro" or "Remix" is
  clearly not about the tool (e.g. a food post, an astrology meme, a band name), exclude it.

Cost-control rule:

- If a chunk has no meaningful discussion of any of the named tools, write one sentence
  beginning `Not relevant:` and stop. Do not invent placeholder sections.

Use only the supplied Reddit content. Do not import outside benchmarks or release notes.
