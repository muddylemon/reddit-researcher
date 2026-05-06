For each product in the search terms, produce a buyer-oriented research note grounded in the
supplied Reddit posts and comments.

For each product, output a Markdown section with these sub-headings:

1. **Headline** — one sentence on how owners actually feel after living with it.
2. **What lasts / what breaks** — 2–4 bullets of recurring durability or failure patterns.
   Be specific: "ear pads flake after ~18 months in three reports" beats "build quality issues".
   Cite post or comment ids.
3. **Common complaints** — non-durability issues that keep coming up (comfort, software,
   pairing, repairability). Cite ids.
4. **What people switched to** — when owners replace this product, what do they choose, and why?
   Skip if the data does not actually contain switch stories.
5. **Worth it?** — one or two sentences capturing the community's current verdict on whether
   to buy this at current price.

Rules of evidence:

- A single bad review is not a pattern. Require multiple independent owners reporting the
  same issue before flagging it.
- Distinguish manufacturing-defect stories from inherent design flaws. Both matter, but
  they imply different buyer responses.
- Beware of "I just got mine and I love it" hype with zero ownership time. Discount it.

Cost-control rule:

- If a chunk is dominated by spec sheets, sale alerts, or off-topic discussion with no
  ownership signal, write one sentence beginning `Not relevant:` and stop.

Use only the supplied Reddit content. Do not import outside reviews or measurement data.
