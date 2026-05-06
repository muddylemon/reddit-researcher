from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class RunLogger:
    def __init__(self, run_dir: Path, *, log_name: str = "scrape.log", echo: bool = True) -> None:
        self.log_path = run_dir / "logs" / log_name
        self.echo = echo
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {message}"
        with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")
        if self.echo:
            print(line, flush=True)
