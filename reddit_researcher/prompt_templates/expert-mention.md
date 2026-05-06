# Track Reddit mentions of named people (search mode).

For each search term, determine whether the supplied Reddit posts and comments are
meaningfully about the named person.

Cost-control rule:

- If a chunk has no meaningful evidence for the named person, write exactly one sentence
  beginning `Not relevant:` and stop. Do not add headings, summaries, or commentary for
  irrelevant chunks.
- If the name match is a different person, a generic word match, a long citation dump,
  OCR/image noise, or an unrelated subreddit discussion, use the same one-sentence
  `Not relevant:` format.

When the chunk does have meaningful discussion, output a Markdown section per person with:

- A concise relevance judgment: substantial discussion, limited mentions, ambiguous
  identity, or no meaningful evidence.
- A summary of the Reddit context: which subreddits, what posts are about, and why the
  person came up.
- A summary of the commentary: praise, criticism, recurring questions, skepticism,
  anecdotes, links to interviews/books/talks, and disagreements.
- Representative post or comment ids in brackets when they support a point.

Do not treat a name match as meaningful by itself. Note uncertainty clearly when identity
or context is unclear. Use only the supplied Reddit content.
