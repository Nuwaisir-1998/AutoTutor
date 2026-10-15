"""End-to-end run of the learning loop through the CLI, playing the subagents' parts."""

import io
import json
import sys

import pytest

from autotutor import cli, service
from autotutor.config import Config
from autotutor.core import scheduler
from autotutor.schemas import (
    AssessmentItem, CapstoneExam, CriterionScore, Grade, Misconception, RubricCriterion,
    Skill, SkillGraph,
)
from autotutor.storage.db import DB


def _skill(sid, prereqs=()):
    return Skill(
        id=sid, name=sid, description="d", prerequisites=list(prereqs), required_levels=[2, 3],
        key_ideas=["k"], key_papers=[],
        common_misconceptions=[Misconception(id=f"{sid}_m", description="wrong idea")],
    )


GRAPH = SkillGraph(
    concept="attention", summary="s", research_frontier=["open"],
    skills=[_skill("dot_product"), _skill("scaled_attention", ["dot_product"])],
)

RUBRIC = [RubricCriterion(criterion="core idea", points=6), RubricCriterion(criterion="detail", points=4)]


def _item(level=2, skills=("dot_product",)):
    return AssessmentItem(
        prompt="Q?", item_type="explain", bloom_level=level, skills_tested=list(skills),
        rubric=RUBRIC, reference_answer="SECRET-REFERENCE", targeted_misconceptions=[],
    )


def _grade(good: bool) -> str:
    return Grade(
        criterion_scores=[
            CriterionScore(criterion=c.criterion, awarded=c.points if good else 0,
                           max_points=c.points, justification="j")
            for c in RUBRIC
        ],
        misconceptions_observed=[] if good else [Misconception(id="x_m", description="x")],
        feedback="fb",
    ).model_dump_json()


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """Call the CLI like Claude Code does; returns (exit code, stdout)."""
    monkeypatch.setattr(cli, "CONFIG", Config(db_path=tmp_path / "t.db"))

    def _run(*args, stdin=""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        code = cli.main(list(args))
        out = capsys.readouterr()
        return code, out.out + out.err
    return _run


def _json(out):
    return json.loads(out)


def test_full_loop_reaches_mastery_and_schedules_reviews(run):
    assert _json(run("next", "attention")[1])["kind"] == "plan"
    code, _ = run("create", "attention", stdin=GRAPH.model_dump_json())
    assert code == 0
    run("rate", "attention", "dot_product=0", "scaled_attention=0")

    answers = iter([False] + [True] * 50)  # first answer wrong, then all right
    seen = []
    for _ in range(60):
        step = _json(run("next", "attention")[1])
        seen.append(step["kind"])
        if step["kind"] == "done":
            break
        if step["kind"] == "teach":
            assert "Tutor brief" in run("tutor-brief", "attention", step["skill_id"], str(step["level"]))[1]
            run("taught", "attention", step["skill_id"])
            continue
        if step["kind"] == "capstone":
            exam = CapstoneExam(items=[_item(6, ["dot_product", "scaled_attention"])])
            ids = _json(run("add-item", "attention", "--kind", "capstone",
                            stdin=exam.model_dump_json())[1])["item_ids"]
        else:
            assert step["kind"] in ("assess", "review")
            ids = _json(run("add-item", "attention", "--kind", step["kind"], "--skill",
                            step["skill_id"], "--level", str(step["level"]),
                            stdin=_item(step["level"]).model_dump_json())[1])["item_ids"]
        for i in ids:
            view = run("show-item", str(i))[1]
            assert "Q?" in view and "SECRET-REFERENCE" not in view  # learner never sees it
            good = next(answers)
            run("answer", str(i), stdin="good answer" if good else "wrong")
            assert "SECRET-REFERENCE" in run("grading-packet", str(i))[1]
            result = _json(run("grade", str(i), stdin=_grade(good))[1])
            assert result["passed"] is good

    assert seen[:3] == ["teach", "assess", "teach"]  # failure triggers re-teaching
    assert seen[-2:] == ["capstone", "done"]
    db = DB(cli.CONFIG.db_path)
    concept = db.get_concept("attention")
    assert concept.capstone_passed_at is not None
    assert all(st.mastered_at and st.review_due_at for st in db.get_states(concept.id).values())
    assert "Capstone passed" in run("status", "attention")[1]


def test_open_item_is_resumed_before_anything_else(run):
    run("create", "attention", stdin=GRAPH.model_dump_json())
    ids = _json(run("add-item", "attention", "--kind", "assess", "--skill", "dot_product",
                    "--level", "2", stdin=_item().model_dump_json())[1])["item_ids"]
    step = _json(run("next", "attention")[1])
    assert (step["kind"], step["item_id"]) == ("answer_item", ids[0])
    run("answer", str(ids[0]), stdin="x")
    assert _json(run("next", "attention")[1])["kind"] == "grade_item"


def test_grader_cannot_inflate_score_by_omitting_or_resizing_criteria(run):
    run("create", "attention", stdin=GRAPH.model_dump_json())
    (iid,) = _json(run("add-item", "attention", "--kind", "assess", "--skill", "dot_product",
                       "--level", "2", stdin=_item().model_dump_json())[1])["item_ids"]
    run("answer", str(iid), stdin="partial")
    sneaky = Grade(
        criterion_scores=[CriterionScore(criterion="core idea", awarded=6, max_points=6, justification="")],
        misconceptions_observed=[], feedback="",
    ).model_dump_json()
    result = _json(run("grade", str(iid), stdin=sneaky)[1])
    assert result["score"] == 0.6 and result["passed"] is False


def test_bad_json_is_a_clean_error(run):
    code, out = run("create", "attention", stdin="{not json")
    assert code == 2 and "Invalid SkillGraph JSON" in out


def test_review_due_after_a_day(tmp_path):
    db = DB(tmp_path / "x.db")
    c = db.create_concept("attention", GRAPH)
    for st in db.get_states(c.id).values():
        st.p_known, st.passed_levels = 0.99, [2, 3]
        scheduler.on_mastered(st, now=0)
        db.save_state(c.id, st)
    db.set_capstone_passed(c.id, 1.0)
    step = service.next_step(db, "attention", Config(), now=2 * scheduler.DAY)
    assert step["kind"] == "review"
    assert service.due_concepts(db, now=2 * scheduler.DAY) == ["attention"]
