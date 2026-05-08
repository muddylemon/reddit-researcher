---
name: setup
description: Use when the user has just cloned reddit-researcher or asks to verify their environment is ready - checks Python version, venv, editable install, Ollama reachability, and a pulled model, then offers to fix each gap interactively. Invoke for "set up reddit-researcher", "check my environment", "is everything ready to run?", or after a fresh clone.
---

# Setting up reddit-researcher

Use this skill on a fresh clone, or any time the user asks "am I set up correctly?".
The goal is a complete, fail-fast diagnostic of every install-time requirement, with a
proposed fix for each gap. The user retains veto on every install command.

## How to use this skill

Run the seven checks below **in order**, but DO NOT short-circuit on the first failure.
Print a one-line ✓ or ✗ + reason for each check, then loop back over every ✗ in turn
and offer the remediation command. Confirm individually before running each — never
batch them.

When all checks pass (or the user has declined remaining fixes), end with:

> Setup looks good — want to run `/tutorial` for a 3-minute getting-started walkthrough?

Do not auto-invoke `/tutorial`; the user opts in.

## Platform

Commands below are PowerShell (the repo's primary platform). On bash / zsh,
substitute:

- `.venv\Scripts\reddit-researcher.exe` → `.venv/bin/reddit-researcher`
- `.venv\Scripts\pip.exe` → `.venv/bin/pip`
- `.venv\Scripts\Activate.ps1` → `source .venv/bin/activate`
- `Test-Path <path>` → `test -e <path>`

Print the POSIX-equivalent command and ask the user to run it themselves; do not
auto-execute on POSIX in v1.

## Pre-flight checks

### Check 1 — Python ≥ 3.11

Run `python --version` (or `py -3 --version` if `python` isn't on PATH). Parse the
reported version and compare against `3.11`.

- ✗ if missing or older. Print the actual version and tell the user to install /
  upgrade Python 3.11+. **Not auto-fixable** — do not offer to install Python.

### Check 2 — `.venv\` exists at repo root

Use the Read tool on `.venv\Scripts\python.exe`. A "file not found" error means the
venv is missing.

- ✗ if missing. Offer:

  ```powershell
  python -m venv .venv
  ```

  After running, also queue Check 3's remediation in the same flow — a fresh venv
  has no editable install.

### Check 3 — `reddit-researcher` console script present

Use the Read tool on `.venv\Scripts\reddit-researcher.exe`. A "file not found" error
means the editable install hasn't run.

- ✗ if missing. Offer:

  ```powershell
  .venv\Scripts\Activate.ps1
  .venv\Scripts\pip.exe install -e ".[dev]"
  ```

  The activation only persists for the calling shell; the `pip install` is the
  load-bearing one. Use the PowerShell tool.

### Check 4 — Editable install isn't stale

Run `.venv\Scripts\pip.exe show reddit-researcher` and parse the `Version:` line.
Compare against the `version = "..."` line in `pyproject.toml` (use the Grep tool:
pattern `^version = `, glob `pyproject.toml`).

- ✗ if mismatched (most often after a `git pull` that bumped the version without
  a re-install). Offer:

  ```powershell
  .venv\Scripts\pip.exe install -e ".[dev]"
  ```

### Check 5 — Ollama reachable

Use the Bash tool: `curl -sf http://127.0.0.1:11434/api/tags`. Honor `$env:OLLAMA_URL`
if set. A 0 exit code with a JSON body is ✓.

- ✗ on connection refused / non-zero exit. Tell the user:

  > Ollama isn't reachable at the URL above. Open a separate terminal and run
  > `ollama serve`, then leave it running.

  **Do not** spawn `ollama serve` from this skill — it's a long-lived process the
  user should own.

### Check 6 — At least one model pulled

If Check 5 passed, parse the `models[]` array from the same `/api/tags` response.
Empty list is ✗.

- ✗ if no models. Offer:

  ```powershell
  ollama pull qwen3:8b
  ```

  Confirm explicitly before running — this is roughly a 5 GB download. If the user
  balks, point at `docs/model-recommendations.md` for hardware-specific
  alternatives. If Check 5 was ✗, Check 6 is unevaluable; print "skipped — Ollama
  not reachable" and move on.

### Check 7 — PRAW extras (conditional)

Only run this check if at least one project uses PRAW. Use the Grep tool with
`pattern = 'backend\s*=\s*"praw"'` and `glob = 'projects/*/project.toml'`. If no
matches, **skip the check entirely** (no ✓ / ✗ printed).

If matches exist:

- Run `.venv\Scripts\pip.exe show praw`. ✗ if not installed; offer
  `.venv\Scripts\pip.exe install -e ".[praw]"`.
- Use the Read tool on `.env` (repo root) and the matched project's `.env`. Look
  for `REDDIT_CLIENT_ID`. ✗ if absent in both. Point at the README's "Authenticated
  scraping (PRAW backend)" section. **Do not write `.env` for the user** —
  credentials are sensitive.

## Confirmation pattern

For every ✗, the offer is: print the failing check, the exact command, then ask the
user Y/N. A "no" on one fix doesn't block subsequent fixes — continue down the list
and let the user fix the rest themselves later.

After all confirmable fixes have been processed (run or declined), re-run the affected
checks to confirm they now pass. Print a final ✓/✗ summary line per check.

## Anti-patterns

- Running `pip install` or `ollama pull` without confirmation, even after a blanket
  "yes fix everything" — every install is its own decision.
- Editing the user's `.env`. Diagnose, point at docs, stop.
- Spawning `ollama serve`. Long-lived processes belong to the user.
- Recommending `qwen3:8b` on a machine with too little RAM. Don't try to read system
  specs — surface `docs/model-recommendations.md` if the user pushes back.
- Continuing past a ✗ Check 5 (Ollama unreachable) without flagging that Checks 6 and
  7 can't be fully evaluated until it's fixed.
- Auto-invoking `/tutorial` after setup completes. Print the offer line and stop;
  let the user opt in.
