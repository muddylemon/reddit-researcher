#!/usr/bin/env bash
# Run the example subreddit project end-to-end.
# Assumes the venv is activated and Ollama is serving qwen3:8b.

set -euo pipefail

cd "$(dirname "$0")/.."

reddit-researcher run projects/example-subreddit-faq
