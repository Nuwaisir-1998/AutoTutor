"""The cognitive ladder a skill must be climbed on, adapted for ML research.

Classic Bloom's taxonomy, re-cut for what a researcher who publishes at top venues
must be able to do with an idea: not just explain it, but derive it, build it,
diagnose it, review others' claims about it, and push it forward.
"""

from __future__ import annotations

LEVELS: dict[int, tuple[str, str]] = {
    1: ("recall", "State definitions, notation, and canonical results accurately."),
    2: ("explain", "Explain the idea and its intuition in your own words, as if teaching a new PhD student."),
    3: ("derive", "Reproduce the key derivations or proofs, and know which assumptions each step needs."),
    4: ("implement", "Implement it from scratch (NumPy/PyTorch-level) and get the numerical details right."),
    5: ("analyze", "Predict and diagnose behaviour: failure modes, ablations, scaling, hyperparameter sensitivity."),
    6: ("critique", "Review a paper's claims about it like a top-venue reviewer: spot flawed baselines, leakage, weak stats."),
    7: ("create", "Design rigorous experiments or propose a novel, publishable extension with a clear hypothesis."),
}

MIN_LEVEL = min(LEVELS)
MAX_LEVEL = max(LEVELS)


def name(level: int) -> str:
    return LEVELS[level][0]


def describe(level: int) -> str:
    label, desc = LEVELS[level]
    return f"L{level} {label}: {desc}"


def ladder_text() -> str:
    return "\n".join(describe(lvl) for lvl in sorted(LEVELS))


def normalize_levels(levels: list[int]) -> list[int]:
    """Clamp to the valid range, dedupe, sort. Never returns an empty list."""
    cleaned = sorted({min(MAX_LEVEL, max(MIN_LEVEL, int(lvl))) for lvl in levels})
    return cleaned or [2]
