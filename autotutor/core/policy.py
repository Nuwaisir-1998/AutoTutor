"""Deterministic curriculum policy: what should happen next?

Kept free of I/O and LLM calls so it is predictable and unit-testable. The LLM roles
decide *how* to teach and assess; this decides *what* and *when*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from autotutor.core import scheduler
from autotutor.core.learner_model import TEST_OUT_PRIOR, SkillState
from autotutor.core.skill_graph import topo_order
from autotutor.schemas import SkillGraph

ActionKind = Literal["review", "teach", "assess", "capstone", "done"]


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    skill_id: str | None = None
    level: int | None = None


def next_action(
    graph: SkillGraph,
    states: dict[str, SkillState],
    *,
    capstone_passed: bool,
    now: float,
    mastery_p: float,
    prereq_p: float,
) -> Action:
    skills = {s.id: s for s in graph.skills}

    # 1. Retention reviews that are due come first: forgetting is cheapest to fix early.
    due = [st for st in states.values() if st.skill_id in skills and scheduler.is_due(st, now)]
    if due:
        st = min(due, key=lambda s: s.review_due_at or 0.0)
        return Action("review", st.skill_id, max(skills[st.skill_id].required_levels))

    # 2. Next unmastered skill whose prerequisites are solid, in curriculum order.
    order = topo_order(graph)
    unmastered = [
        sid for sid in order
        if not states[sid].is_mastered(skills[sid].required_levels, mastery_p)
    ]
    if unmastered:
        ready = [
            sid for sid in unmastered
            if all(states[p].p_known >= prereq_p for p in skills[sid].prerequisites)
        ]
        # Fallback can't normally trigger (roots have no prerequisites), but never stall.
        sid = ready[0] if ready else min(unmastered, key=lambda s: states[s].p_known)
        st = states[sid]
        level = st.next_level(skills[sid].required_levels)
        if st.pending_assessment:
            return Action("assess", sid, level)
        if st.attempts == 0 and st.p_known >= TEST_OUT_PRIOR:
            return Action("assess", sid, level)  # let a confident learner test out
        return Action("teach", sid, level)

    # 3. Every skill mastered: integrative transfer exam, then we're done (modulo reviews).
    if not capstone_passed:
        return Action("capstone")
    return Action("done")
