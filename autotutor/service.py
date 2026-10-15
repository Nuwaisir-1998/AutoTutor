"""Operations behind each CLI command.

Claude Code (the tutor) and its subagents (planner, examiner, grader) do the
language work; this module owns state, mastery decisions, and what happens next.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

from autotutor.config import Config
from autotutor.core import bloom, scheduler
from autotutor.core.learner_model import SELF_RATING_PRIOR, SkillState, apply_result
from autotutor.core.policy import next_action
from autotutor.core.skill_graph import sanitize, topo_order
from autotutor.schemas import AssessmentItem, CapstoneExam, Grade, RubricCriterion, Skill, SkillGraph
from autotutor.storage.db import DB, Concept, ItemRow, LearnerProfile

CAPSTONE_ITEMS = 3

DEFAULT_PROFILE = LearnerProfile(
    background="Graduate-level ML student; comfortable with Python, linear algebra, probability.",
    goal="Publish highest-quality papers at top ML conferences and journals.",
    venues="NeurIPS, ICML, ICLR, JMLR, TPAMI",
)


class UserError(Exception):
    """A problem with the request (unknown concept, bad JSON); reported without a traceback."""


def profile(db: DB) -> LearnerProfile:
    p = db.get_learner()
    if p is None:
        p = DEFAULT_PROFILE
        db.save_learner(p)
    return p


def require_concept(db: DB, name: str) -> Concept:
    c = db.get_concept(name)
    if c is None:
        raise UserError(f"Unknown concept: {name!r}. Plan it first.")
    return c


def skill_of(concept: Concept, skill_id: str) -> Skill:
    for s in concept.graph.skills:
        if s.id == skill_id:
            return s
    raise UserError(f"Unknown skill {skill_id!r} in {concept.name!r}.")


# --- what next ----------------------------------------------------------------------

def next_step(db: DB, name: str, config: Config, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    concept = db.get_concept(name)
    if concept is None:
        return {"kind": "plan", "concept": name}

    open_items = db.open_items(concept.id)
    if open_items:
        row = open_items[0]
        kind = "grade_item" if row.answer is not None else "answer_item"
        return {"kind": kind, "concept": concept.name, "item_id": row.id, "item_kind": row.kind}

    states = db.get_states(concept.id)
    action = next_action(
        concept.graph, states, capstone_passed=concept.capstone_passed_at is not None,
        now=now, mastery_p=config.mastery_p, prereq_p=config.prereq_p,
    )
    out: dict[str, Any] = {"kind": action.kind, "concept": concept.name}
    if action.skill_id:
        out.update(
            skill_id=action.skill_id,
            skill_name=skill_of(concept, action.skill_id).name,
            level=action.level,
            level_name=bloom.name(action.level),
        )
    return out


# --- planning -----------------------------------------------------------------------

def create_concept(db: DB, name: str, graph_json: str) -> Concept:
    if db.get_concept(name) is not None:
        raise UserError(f"Concept {name!r} already exists.")
    try:
        graph = SkillGraph.model_validate_json(graph_json)
    except ValueError as e:
        raise UserError(f"Invalid SkillGraph JSON: {e}") from e
    graph = sanitize(graph)
    if not graph.skills:
        raise UserError("The skill graph has no skills.")
    return db.create_concept(name, graph)


def rate(db: DB, concept: Concept, ratings: dict[str, int]) -> None:
    states = db.get_states(concept.id)
    for sid, r in ratings.items():
        skill_of(concept, sid)
        if r not in SELF_RATING_PRIOR:
            raise UserError(f"Rating for {sid} must be 0-3.")
        st = states[sid]
        if st.attempts == 0:  # self-ratings only seed the prior; evidence overrides them
            st.p_known = SELF_RATING_PRIOR[r]
            db.save_state(concept.id, st)


# --- tutoring -----------------------------------------------------------------------

def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def tutor_brief(db: DB, concept: Concept, skill_id: str, level: int) -> str:
    skill = skill_of(concept, skill_id)
    st = db.get_states(concept.id)[skill_id]
    p = profile(db)
    passed = ", ".join(f"L{l} {bloom.name(l)}" for l in st.passed_levels) or "(none yet)"
    return f"""# Tutor brief: {skill.name} ({skill.id})

Concept: {concept.graph.concept}
Learner: {p.background} Goal: {p.goal} Venues: {p.venues}

{skill.description}

## Key ideas
{_bullets(skill.key_ideas)}

## Common misconceptions for this skill
{_bullets([m.description for m in skill.common_misconceptions])}

## Key papers
{_bullets(skill.key_papers)}

Prerequisites already solid: {", ".join(skill.prerequisites) or "(none)"}

## Where the learner stands
- P(knows this skill): {st.p_known:.2f}
- Levels passed: {passed}
- Misconceptions observed in their graded answers (address head-on):
{_bullets([f"{k}: {v}" for k, v in st.misconceptions.items()])}
- Most recent examiner feedback: {db.last_feedback(concept.id, skill_id) or "(none yet)"}

## Target for the upcoming assessment
{bloom.describe(level)}
"""


def mark_taught(db: DB, concept: Concept, skill_id: str) -> None:
    skill_of(concept, skill_id)
    st = db.get_states(concept.id)[skill_id]
    st.pending_assessment = True
    db.save_state(concept.id, st)


# --- examining ----------------------------------------------------------------------

def _skill_brief(skill: Skill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "key_ideas": skill.key_ideas,
        "known_misconceptions": {m.id: m.description for m in skill.common_misconceptions},
        "key_papers": skill.key_papers,
    }


def examiner_brief(
    db: DB, concept: Concept, kind: str, skill_id: str | None, level: int | None
) -> dict[str, Any]:
    p = profile(db)
    base = {"concept": concept.graph.concept, "learner": p.__dict__, "ladder": bloom.ladder_text()}
    if kind == "capstone":
        return base | {
            "task": f"Write a capstone exam of exactly {CAPSTONE_ITEMS} items (CapstoneExam JSON). "
                    "The learner has passed every skill individually; test whether they can "
                    "INTEGRATE them in unseen situations. Each item must exercise at least two "
                    "skills: one L6 paper_critique, one L7 experiment_design or research_proposal "
                    "(ideally on the research frontier), and one L5 analysis or L3 derivation that "
                    "transfers the core idea to an unfamiliar setting.",
            "research_frontier": concept.graph.research_frontier,
            "skills": [_skill_brief(s) for s in concept.graph.skills],
            "previously_asked": db.recent_item_prompts(concept.id, None),
        }
    if skill_id is None or level is None:
        raise UserError("assess/review items need --skill and --level.")
    skill = skill_of(concept, skill_id)
    st = db.get_states(concept.id)[skill_id]
    return base | {
        "task": f"Write ONE assessment item (AssessmentItem JSON) at {bloom.describe(level)}",
        "skill": _skill_brief(skill),
        "target_level": level,
        "learner_misconceptions_to_target": st.misconceptions,
        "previously_asked": db.recent_item_prompts(concept.id, skill_id),
    }


def _clean(item: AssessmentItem, level: int, valid: set[str], default: list[str]) -> AssessmentItem:
    item.bloom_level = level
    item.skills_tested = [s for s in item.skills_tested if s in valid] or default
    item.rubric = [c for c in item.rubric if c.points > 0] or [
        RubricCriterion(criterion="Answer matches the reference answer in substance.", points=10)
    ]
    return item


def add_items(
    db: DB, concept: Concept, kind: str, skill_id: str | None, level: int | None, payload: str
) -> list[int]:
    valid = {s.id for s in concept.graph.skills}
    try:
        if kind == "capstone":
            exam = CapstoneExam.model_validate_json(payload)
            if not exam.items:
                raise UserError("Capstone exam has no items.")
            batch = db.next_batch(concept.id)
            return [
                db.add_item(
                    concept.id, None, "capstone",
                    _clean(it, bloom.normalize_levels([it.bloom_level])[0], valid, sorted(valid)),
                    batch,
                )
                for it in exam.items
            ]
        if kind not in ("assess", "review") or skill_id is None or level is None:
            raise UserError("assess/review items need --skill and --level.")
        skill_of(concept, skill_id)
        item = _clean(AssessmentItem.model_validate_json(payload), level, valid, [skill_id])
        item.skills_tested = [skill_id]  # a per-skill item is evidence about that skill only
        return [db.add_item(concept.id, skill_id, kind, item)]
    except ValueError as e:
        raise UserError(f"Invalid item JSON: {e}") from e


def learner_view(db: DB, row: ItemRow) -> str:
    """What the learner may see: the question only, never rubric or reference answer."""
    concept = db.get_concept_by_id(row.concept_id)
    if row.kind == "capstone":
        n = len(db.batch_items(row.concept_id, row.batch or 0))
        pos = [r.id for r in db.batch_items(row.concept_id, row.batch or 0)].index(row.id) + 1
        title = f"Capstone {pos}/{n}"
    else:
        title = f"{'Retention review' if row.kind == 'review' else 'Assessment'}: " \
                f"{skill_of(concept, row.skill_id).name}"
    lvl = row.item.bloom_level
    return (f"## {title} · L{lvl} {bloom.name(lvl)} · {row.item.item_type} (item #{row.id})\n\n"
            f"{row.item.prompt}\n")


def require_item(db: DB, item_id: int) -> ItemRow:
    row = db.get_item(item_id)
    if row is None:
        raise UserError(f"Unknown item #{item_id}.")
    return row


def submit_answer(db: DB, row: ItemRow, answer: str) -> None:
    if row.grade is not None:
        raise UserError(f"Item #{row.id} is already graded.")
    db.set_answer(row.id, answer)


# --- grading ------------------------------------------------------------------------

def _known_misconceptions(concept: Concept, states: dict[str, SkillState], row: ItemRow) -> dict[str, str]:
    known: dict[str, str] = {}
    for sid in row.item.skills_tested:
        known |= {m.id: m.description for m in skill_of(concept, sid).common_misconceptions}
        known |= states[sid].misconceptions
    return known


def grading_packet(db: DB, row: ItemRow) -> dict[str, Any]:
    if row.answer is None:
        raise UserError(f"Item #{row.id} has no answer yet.")
    concept = db.get_concept_by_id(row.concept_id)
    return {
        "item_id": row.id,
        "bloom_level": row.item.bloom_level,
        "item_type": row.item.item_type,
        "prompt": row.item.prompt,
        "rubric": [c.model_dump() for c in row.item.rubric],
        "reference_answer": row.item.reference_answer,
        "known_misconceptions": _known_misconceptions(concept, db.get_states(concept.id), row),
        "learner_answer": row.answer.strip() or "(empty)",
    }


def submit_grade(
    db: DB, row: ItemRow, grade_json: str, config: Config, now: float | None = None
) -> dict[str, Any]:
    now = time.time() if now is None else now
    if row.answer is None:
        raise UserError(f"Item #{row.id} has no answer yet.")
    if row.grade is not None:
        raise UserError(f"Item #{row.id} is already graded.")
    try:
        grade = Grade.model_validate_json(grade_json)
    except ValueError as e:
        raise UserError(f"Invalid Grade JSON: {e}") from e

    # Re-anchor max points to the rubric so a grader can't move the goalposts.
    rubric = {c.criterion: c.points for c in row.item.rubric}
    for c in grade.criterion_scores:
        c.max_points = rubric.get(c.criterion, c.max_points)
    if not grade.criterion_scores:
        raise UserError("Grade has no criterion scores.")

    # Score against the rubric's total so an omitted criterion counts as zero.
    total = sum(rubric.values())
    got = sum(min(max(0, c.awarded), max(0, c.max_points)) for c in grade.criterion_scores)
    score = min(1.0, got / total) if total else grade.score()
    passed = score >= config.pass_score
    db.set_grade(row.id, grade, score, passed)

    concept = db.get_concept_by_id(row.concept_id)
    states = db.get_states(concept.id)
    observed = {m.id: m.description for m in grade.misconceptions_observed}
    events: list[str] = []
    for sid in row.item.skills_tested:
        events += _update_skill(db, concept, states[sid], row, passed, observed, config, now)

    if row.kind == "capstone":
        batch = db.batch_items(concept.id, row.batch or 0)
        if all(r.grade is not None for r in batch):
            if all(r.passed for r in batch):
                db.set_capstone_passed(concept.id, now)
                events.append("CAPSTONE PASSED. Retention reviews are scheduled at 1, 3 and 7 days.")
            else:
                events.append("Capstone not passed. Skills that slipped will be re-taught, "
                              "then a fresh capstone.")

    return {
        "item_id": row.id,
        "score": round(score, 3),
        "passed": passed,
        "criteria": [
            {"criterion": c.criterion, "points": f"{c.awarded}/{c.max_points}",
             "why": c.justification}
            for c in grade.criterion_scores
        ],
        "misconceptions_observed": observed,
        "feedback": grade.feedback,
        "events": events,
    }


def _update_skill(
    db: DB, concept: Concept, st: SkillState, row: ItemRow, passed: bool,
    observed: dict[str, str], config: Config, now: float,
) -> list[str]:
    skill = skill_of(concept, st.skill_id)
    apply_result(st, level=row.item.bloom_level, passed=passed,
                 targeted=row.item.targeted_misconceptions, observed=observed)
    mastered = st.is_mastered(skill.required_levels, config.mastery_p)
    events: list[str] = []
    if mastered and row.kind == "review" and st.mastered_at is not None:
        scheduler.on_review(st, passed, now)
    elif mastered and st.mastered_at is None:
        scheduler.on_mastered(st, now)
        events.append(f"Skill mastered: {skill.name}")
    elif not mastered and st.mastered_at is not None:
        scheduler.on_lost_mastery(st)
        events.append(f"Skill slipped below mastery: {skill.name} (will be re-taught)")
        if concept.capstone_passed_at is not None:
            db.set_capstone_passed(concept.id, None)
            concept.capstone_passed_at = None
    db.save_state(concept.id, st)
    return events


# --- reporting ----------------------------------------------------------------------

def status_text(db: DB, concept: Concept, config: Config) -> str:
    states = db.get_states(concept.id)
    lines = [f"## {concept.name}", "",
             "| Skill | P(known) | Levels (✓ passed) | Status |", "|---|---|---|---|"]
    n_mastered = 0
    for sid in topo_order(concept.graph):
        s = skill_of(concept, sid)
        st = states[sid]
        mastered = st.is_mastered(s.required_levels, config.mastery_p)
        n_mastered += mastered
        levels = " ".join(f"L{l}{'✓' if l in st.passed_levels else ''}" for l in s.required_levels)
        if mastered:
            due = (dt.datetime.fromtimestamp(st.review_due_at).strftime("%b %d %H:%M")
                   if st.review_due_at else "-")
            status = (f"mastered · retention {st.review_stage}/"
                      f"{scheduler.RETENTION_STAGES_REQUIRED} · next review {due}")
        elif st.attempts:
            status = f"in progress · {st.attempts} attempts"
        else:
            status = "not started"
        lines.append(f"| {s.name} | {st.p_known:.2f} | {levels} | {status} |")

    retained = all(scheduler.retention_verified(st) for st in states.values())
    lines.append("")
    if concept.capstone_passed_at and retained:
        lines.append("**MASTERED**: capstone passed and retention verified.")
    elif concept.capstone_passed_at:
        lines.append("**Capstone passed**: retention reviews pending.")
    else:
        lines.append(f"{n_mastered}/{len(concept.graph.skills)} skills mastered.")
    return "\n".join(lines)


def graph_text(concept: Concept) -> str:
    g = concept.graph
    lines = [f"## {g.concept}", g.summary, ""]
    for sid in topo_order(g):
        s = skill_of(concept, sid)
        pre = f" ← {', '.join(s.prerequisites)}" if s.prerequisites else ""
        levels = " ".join(f"L{l}" for l in s.required_levels)
        lines.append(f"- **{s.name}** `{s.id}` [{levels}]{pre}: {s.description}")
    if g.research_frontier:
        lines += ["", "**Research frontier**"] + [f"- {p}" for p in g.research_frontier]
    return "\n".join(lines)


def due_concepts(db: DB, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    return [
        c.name for c in db.list_concepts()
        if any(scheduler.is_due(st, now) for st in db.get_states(c.id).values())
    ]


def schema_json(name: str) -> str:
    models = {m.__name__: m for m in (SkillGraph, AssessmentItem, CapstoneExam, Grade)}
    if name not in models:
        raise UserError(f"Unknown schema {name!r}; choose from {', '.join(models)}.")
    return json.dumps(models[name].model_json_schema(), indent=2)
