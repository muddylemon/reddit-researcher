# Local model recommendations

This is a pragmatic guide, not a benchmark. Reddit Researcher is a small CLI; what matters is
that the model runs comfortably in your VRAM and is good enough at instruction-following to
honor the prompt.

## TL;DR

| Hardware                         | Try first             | Why                                           |
|----------------------------------|-----------------------|-----------------------------------------------|
| 8 GB VRAM (e.g. 3060/4060)       | `qwen3:8b`            | Fits in VRAM, decent reasoning for the size.  |
| 12–16 GB VRAM (e.g. 4070/4080)   | `qwen3:14b`           | Sweet spot for synthesis quality.             |
| 24 GB VRAM (e.g. 3090/4090)      | `qwen3:30b`           | Strong instruction-following + long context.  |
| Apple Silicon (16+ GB unified)   | `qwen3:8b` or `qwen3:14b` | Memory-bound; smaller is friendlier.       |

Always run `ollama pull <tag>` before pointing the tool at a model — Reddit Researcher will
complain (with a list of installed tags) if the requested model is missing.

## How to choose

Two questions matter for this tool:

1. **Does it fit in VRAM?** Spilling to system RAM/CPU drops throughput by an order of magnitude.
   Pick the largest model that stays in VRAM at your usual quantization.
2. **Is it good at "follow this prompt and only use the supplied data"?** Smaller models often
   pad output, hallucinate cited ids, or ignore cost-control rules like the `Not relevant:` short
   form. If that's happening, step up a size class.

For research where you'll re-run extraction many times against the same scrape, prefer a model
big enough to get the prompt right on the first pass. Inference is local; the cost is your wall
time.

## Prompt-side knobs

Independent of the model:

- Use `chunk_char_limit = 12000` as a starting point. Larger chunks reduce repetition between
  chunks; smaller chunks help small models stay focused.
- For prompts with a `Not relevant:` short form, set `temperature` low via the `[analyze]` table
  (the default Ollama setting is fine for synthesis but a touch high for filtering).

## Don't bother with 70B+ on a single 24 GB card

You can technically run quantized 70B models with offloading. For this tool's workload — many
short-to-medium chunks, fast iteration on prompts — the throughput hit is not worth it. Use a
mid-size model that fits comfortably in VRAM and iterate on the prompt instead.
