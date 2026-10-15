"""Validation and ordering of planner-produced skill graphs."""

from __future__ import annotations

import re

from autotutor.core import bloom
from autotutor.schemas import SkillGraph


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "skill"


def sanitize(graph: SkillGraph) -> SkillGraph:
    """Make a planner graph safe to drive the curriculum.

    Unique snake_case ids, prerequisites that point at real skills, no self-loops,
    no cycles (back edges are dropped), and valid Bloom levels.
    """
    graph = graph.model_copy(deep=True)
    seen: set[str] = set()
    renames: dict[str, str] = {}
    for skill in graph.skills:
        new_id = base = _slug(skill.id or skill.name)
        n = 2
        while new_id in seen:
            new_id = f"{base}_{n}"
            n += 1
        seen.add(new_id)
        renames.setdefault(skill.id, new_id)
        skill.id = new_id

    for skill in graph.skills:
        prereqs = [renames.get(p, _slug(p)) for p in skill.prerequisites]
        skill.prerequisites = list(dict.fromkeys(p for p in prereqs if p in seen and p != skill.id))
        skill.required_levels = bloom.normalize_levels(skill.required_levels)

    _break_cycles(graph)
    return graph


def _break_cycles(graph: SkillGraph) -> None:
    by_id = {s.id: s for s in graph.skills}
    state: dict[str, int] = {}  # 1 = on stack, 2 = done

    def visit(sid: str) -> None:
        state[sid] = 1
        skill = by_id[sid]
        kept = []
        for p in skill.prerequisites:
            if state.get(p) == 1:
                continue  # back edge -> cycle; drop it
            if state.get(p) is None:
                visit(p)
            kept.append(p)
        skill.prerequisites = kept
        state[sid] = 2

    for s in graph.skills:
        if s.id not in state:
            visit(s.id)


def topo_order(graph: SkillGraph) -> list[str]:
    """Prerequisites first; ties keep the planner's order. Assumes a sanitized graph."""
    order: list[str] = []
    placed: set[str] = set()
    remaining = [s for s in graph.skills]
    while remaining:
        progressed = False
        for s in list(remaining):
            if all(p in placed for p in s.prerequisites):
                order.append(s.id)
                placed.add(s.id)
                remaining.remove(s)
                progressed = True
                break
        if not progressed:  # cannot happen after sanitize(); fail safe
            order.extend(s.id for s in remaining)
            break
    return order
