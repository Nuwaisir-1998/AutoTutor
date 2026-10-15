"""Spaced-retention checks after a skill is mastered.

Expanding intervals (1, 3, 7, 21 days). Passing a review advances the stage; failing
resets it, and the BKT update from the failed attempt usually drops the skill below
mastery so the orchestrator re-teaches it.
"""

from __future__ import annotations

from autotutor.core.learner_model import SkillState

DAY = 86_400.0
REVIEW_INTERVALS_DAYS = [1, 3, 7, 21]

# Reviews (1d, 3d, 7d) that must be passed before retention counts as verified.
RETENTION_STAGES_REQUIRED = 3


def on_mastered(state: SkillState, now: float) -> None:
    if state.mastered_at is None:
        state.mastered_at = now
        state.review_stage = 0
        state.review_due_at = now + REVIEW_INTERVALS_DAYS[0] * DAY


def on_review(state: SkillState, passed: bool, now: float) -> None:
    if passed:
        state.review_stage += 1
        idx = min(state.review_stage, len(REVIEW_INTERVALS_DAYS) - 1)
        state.review_due_at = now + REVIEW_INTERVALS_DAYS[idx] * DAY
    else:
        state.review_stage = 0
        state.review_due_at = now + REVIEW_INTERVALS_DAYS[0] * DAY


def on_lost_mastery(state: SkillState) -> None:
    state.mastered_at = None
    state.review_stage = 0
    state.review_due_at = None


def is_due(state: SkillState, now: float) -> bool:
    return state.review_due_at is not None and state.review_due_at <= now


def retention_verified(state: SkillState) -> bool:
    return state.review_stage >= RETENTION_STAGES_REQUIRED
