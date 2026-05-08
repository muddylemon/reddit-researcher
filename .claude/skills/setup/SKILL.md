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

## Confirmation pattern

(filled in by Task 4)

## Anti-patterns

(filled in by Task 4)
