"""Per-skill learner state: Bayesian Knowledge Tracing plus the Bloom-level ladder.

A skill is mastered only when BOTH hold:
  * BKT says P(known) >= mastery threshold, and
  * the learner has passed an item at every Bloom level the skill requires.
The first guards against lucky streaks; the second against shallow understanding.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Self-rating during onboarding -> BKT prior.
SELF_RATING_PRIOR = {0: 0.05, 1: 0.2, 2: 0.4, 3: 0.6}

# At or above this prior the learner is assessed before being taught ("test out").
TEST_OUT_PRIOR = 0.4

P_LEARN = 0.15
P_SLIP = 0.1


def p_guess(level: int) -> float:
    # Open-ended research questions are much harder to guess than recall questions.
    return 0.15 if level <= 2 else 0.05


def bkt_update(p_known: float, correct: bool, level: int, p_learn: float = P_LEARN) -> float:
    g, s = p_guess(level), P_SLIP
    if correct:
        posterior = p_known * (1 - s) / (p_known * (1 - s) + (1 - p_known) * g)
    else:
        posterior = p_known * s / (p_known * s + (1 - p_known) * (1 - g))
    return posterior + (1 - posterior) * p_learn


@dataclass
class SkillState:
    skill_id: str
    p_known: float = SELF_RATING_PRIOR[0]
    passed_levels: list[int] = field(default_factory=list)
    attempts: int = 0
    pending_assessment: bool = False  # set after a teaching episode
    misconceptions: dict[str, str] = field(default_factory=dict)  # id -> description
    mastered_at: float | None = None
    review_stage: int = 0  # number of spaced reviews passed since mastery
    review_due_at: float | None = None

    def is_mastered(self, required_levels: list[int], mastery_p: float) -> bool:
        return self.p_known >= mastery_p and set(required_levels) <= set(self.passed_levels)

    def next_level(self, required_levels: list[int]) -> int:
        """Lowest required level not yet passed; once all are passed, re-test the top one."""
        for lvl in sorted(required_levels):
            if lvl not in self.passed_levels:
                return lvl
        return max(required_levels)


def apply_result(
    state: SkillState,
    *,
    level: int,
    passed: bool,
    targeted: list[str],
    observed: dict[str, str],
) -> SkillState:
    """Fold one graded attempt into the skill's state (mutates and returns it)."""
    state.p_known = bkt_update(state.p_known, passed, level)
    state.attempts += 1
    state.pending_assessment = False
    if passed and level not in state.passed_levels:
        state.passed_levels = sorted(state.passed_levels + [level])
    # Misconceptions: anything the grader saw is active; anything this item was built
    # to expose and the learner still passed without showing it is considered fixed.
    state.misconceptions.update(observed)
    if passed:
        for mid in targeted:
            if mid not in observed:
                state.misconceptions.pop(mid, None)
    return state
