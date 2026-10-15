"""Runtime configuration. Every value can be overridden with an environment variable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Config:
    db_path: Path = field(
        default_factory=lambda: Path(
            _env("AUTOTUTOR_DB", str(Path.home() / ".autotutor" / "autotutor.db"))
        )
    )
    # Mastery thresholds.
    pass_score: float = float(_env("AUTOTUTOR_PASS_SCORE", "0.8"))
    mastery_p: float = float(_env("AUTOTUTOR_MASTERY_P", "0.95"))
    prereq_p: float = float(_env("AUTOTUTOR_PREREQ_P", "0.8"))


CONFIG = Config()
