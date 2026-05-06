# Project ideas

This is a catalog of research projects that fit the Reddit Researcher pipeline. The
shipped examples under [`projects/`](../projects/) cover the most common shapes; this
page is a longer menu for inspiration.

Each idea below is described as a starting point — the actual project folder is yours to
build with `reddit-researcher init`. Skim the **shape** and **why it works** columns to
find one that matches the question you're chasing.

> A note on Reddit-as-data
>
> Reddit's strength as a source is **voluntary, identity-light opinion at scale**, sliced
> by community. A subreddit gives you a self-selected expert (or enthusiast) panel; a
> cross-subreddit search gives you a sentiment heatmap. The pipeline is designed for both.

## What's shipped vs. what's in this catalog

| Shipped example | Catalog idea |
|---|---|
| `example-subreddit-faq`        | The "what does this community keep asking?" template. |
| `example-game-reception`       | The comparative-sentiment template. |
| `example-tool-sentiment`       | The "what do practitioners actually think?" template. |
| `example-product-research`     | The "should I buy this?" template. |

Everything below is in this catalog because it's a riff on one of those four shapes, or
it shows off a Reddit-data strength the shipped set doesn't already cover.

## Comparative sentiment (search mode, multi-term)

Reddit's clearest superpower: opinion at scale, with named subjects. The shipped
`example-game-reception` and `example-tool-sentiment` projects are the canonical
versions of this shape — these riffs swap the subject.

### Public-figure sentiment

- **Mode:** search, no subreddit allowlist (or a broad allowlist).
- **Terms:** 2–3 names — public figures, founders, athletes.
- **Why it works:** general subs talk about people across many threads; the cross-section
  reveals tone and ratio.
- **Watch for:** name collisions (common names need disambiguating context), and brigading
  when a name is contentious. Cite generously so a reader can verify.

### Album / movie / show reception

- **Mode:** search across r/popheads, r/hiphopheads, r/television, r/movies, etc.
- **Terms:** 2–3 recent releases.
- **Why it works:** entertainment subs run dedicated discussion threads on launch and
  again at season/album-end. Use `time_filter = "year"` for a full reception arc.

### Restaurant / chain / service comparisons

- **Mode:** search across r/<city> + r/AskNYC-style locals.
- **Terms:** the chain or restaurant names you're comparing.
- **Why it works:** locals will tell you what tourist guides won't. Allowlist tightens
  results to your geography.

## Buyer / decision research (search mode, focused subreddits)

The shipped `example-product-research` covers this shape. Other angles:

### Used-gear / depreciation research

- **Mode:** search across r/AVexchange, r/MechMarket, r/photomarket, etc.
- **Terms:** product names you're considering buying secondhand.
- **Why it works:** these subs are *exclusively* people transacting and reviewing — the
  noise floor is low and the signal is brutally honest.

### Subscription cancellation patterns

- **Mode:** search across r/personalfinance, r/Frugal, r/<service-name>.
- **Terms:** streaming/SaaS service names.
- **Why it works:** "I just cancelled X because…" is one of Reddit's most reliable post
  templates. Surfaces price-sensitivity and feature-gap themes.

### Travel / destination research

- **Mode:** search across r/travel, r/solotravel, r/<region>.
- **Terms:** destinations or hotels you're weighing.
- **Why it works:** travel subs are dense with "I just went, here's what I'd do
  differently" trip reports.

## Community FAQ mining (subreddit mode)

The shipped `example-subreddit-faq` covers this shape. Other angles:

### Hobby starter pack

- **Mode:** subreddit, e.g. r/woodworking, r/cycling, r/cooking, r/knitting.
- **Sort:** `top`, `time_filter = "all"` to pull canonical "what should a beginner buy?"
  threads.
- **Output:** an unofficial starter-pack post the community would actually endorse.

### Career-advice patterns

- **Mode:** subreddit (r/cscareerquestions, r/AskHR, r/ExperiencedDevs).
- **Sort:** `top`, `time_filter = "month"` for current-cycle advice; `"all"` for evergreen.
- **Output:** what advice does this sub repeat? What's the *bad* advice that keeps showing
  up too?

### Recurring controversies

- **Mode:** subreddit, with a custom sort. Reddit's JSON endpoint accepts
  `sort = "controversial"` — change `VALID_SORTS` in `config.py` if you want this — or use
  `top` and watch for high-comment, low-score posts in the manifest.
- **Output:** a map of the community's open arguments.

## Trend / culture tracking (subreddit mode + recent time filter)

A thinner shape than the others, but Reddit is unusually good at it.

### What's heating up in r/X this month

- **Mode:** subreddit.
- **Sort:** `top`, `time_filter = "week"` or `"month"`.
- **Prompt:** "what's new in this community this cycle? New slang? New controversies?
  New product launches?"
- **Why it works:** monthly comparisons of the same project (rerun and diff manually for
  now) surface emerging topics before they hit broader media. Built-in run diffing is on
  the [roadmap](roadmap.md).

### Slang and emerging vocabulary

- **Mode:** subreddit, in a subculture community (r/2010sNostalgia, niche fandoms).
- **Prompt:** "list terms used in this corpus that a newcomer wouldn't recognize. Define
  each from context."
- **Why it works:** subreddits are where slang gets workshopped before it leaves the building.

## Civic / public-discourse research

Sensitive shape. Use carefully and cite generously — the goal is to summarize what's
*said*, not to amplify any particular take.

### Public reaction to a policy or news event

- **Mode:** search across r/news, r/politics, r/<topic>.
- **Terms:** the policy's name or a stable phrase.
- **Watch for:** brigading, bots, and the well-known left-skew of large default subs.
  Pair with a more domain-specific allowlist when possible.

### Local civic threads

- **Mode:** subreddit, e.g. r/<city>, r/<state>.
- **Prompt:** "what infrastructure / housing / transit issues recur?"
- **Why it works:** city subs are the most-honest local newspaper most cities have.

## Anti-patterns (things this tool does badly)

- **Personal-medical decisions.** The pipeline can summarize what Reddit *says* about a
  health topic, but the corpus is anecdote-heavy and the prompt won't fix that. Use it
  for "what questions do people ask?" not "should I take this drug?".
- **Real-time monitoring.** Reddit's public JSON is rate-limited and snapshot-based.
  This is a research tool, not a streaming feed.
- **Per-user analysis.** Don't try to build "what does u/foo think about X?". The data
  is there, but it's a privacy red flag and the tool doesn't aim that way.
- **Anything that needs full comment trees.** The default fetch caps comments per post.
  Long argumentative threads will be summarized from their top branches only.

## Found a great template?

Open a PR adding it under `projects/example-<name>/`. Keep prompts subject-agnostic where
possible — these are templates other people will fork.
