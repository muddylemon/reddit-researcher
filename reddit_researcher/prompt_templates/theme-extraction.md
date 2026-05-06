# Extract recurring themes from a subreddit (subreddit mode, generic).

Surface the dominant themes in this subreddit's recent discussion. Output a Markdown
report grouped by theme, ranked by how often the theme recurs.

For each theme:

- Give a short noun-phrase title.
- Write one or two sentences describing what people are talking about.
- Include 2–3 representative post or comment ids in brackets, e.g. `[POST abc123]`.
- Note any internal disagreement: split opinions, factional language, or the same
  question being answered differently by different commenters.

After the theme list, add a short "Outliers" section calling out posts that don't fit
any theme but are interesting (genuinely surprising content, sharp contrarian takes,
or unusually high-quality writeups).

Cost-control rule:

- If a chunk is dominated by memes, low-effort content, or off-topic noise with no
  meaningful theme signal, write one sentence beginning `Not relevant:` and stop.

Be evidence-driven. A single hot take is not a theme; require multiple independent
posts or comments before naming one. Use only the supplied Reddit content.
