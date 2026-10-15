from autotutor.core import scheduler
from autotutor.core.learner_model import SkillState, apply_result, bkt_update
from autotutor.core.policy import next_action
from autotutor.core.skill_graph import sanitize, topo_order
from autotutor.schemas import Grade, CriterionScore, Skill, SkillGraph


def skill(sid, prereqs=(), levels=(2, 3)):
    return Skill(
        id=sid, name=sid.title(), description="", prerequisites=list(prereqs),
        required_levels=list(levels), key_ideas=[], common_misconceptions=[], key_papers=[],
    )


def graph(*skills):
    return SkillGraph(concept="c", summary="", skills=list(skills), research_frontier=[])


# --- BKT -----------------------------------------------------------------------------

def test_bkt_moves_in_the_right_direction():
    assert bkt_update(0.3, True, 3) > 0.3
    assert bkt_update(0.9, False, 3) < 0.9


def test_a_few_research_level_passes_reach_mastery_from_low_prior():
    p = 0.05
    for _ in range(3):
        p = bkt_update(p, True, 5)
    assert p >= 0.95


def test_mastery_needs_every_required_level():
    st = SkillState("s", p_known=0.99, passed_levels=[2])
    assert not st.is_mastered([2, 3], 0.95)
    st.passed_levels = [2, 3]
    assert st.is_mastered([2, 3], 0.95)


def test_next_level_climbs_then_retests_top():
    st = SkillState("s", passed_levels=[2])
    assert st.next_level([2, 3, 6]) == 3
    st.passed_levels = [2, 3, 6]
    assert st.next_level([2, 3, 6]) == 6


def test_misconceptions_added_on_observation_and_cleared_when_targeted_and_passed():
    st = SkillState("s")
    apply_result(st, level=2, passed=False, targeted=[], observed={"m1": "bad"})
    assert "m1" in st.misconceptions
    apply_result(st, level=2, passed=True, targeted=["m1"], observed={})
    assert "m1" not in st.misconceptions


def test_grade_score_clamps():
    g = Grade(
        criterion_scores=[
            CriterionScore(criterion="a", awarded=7, max_points=5, justification=""),
            CriterionScore(criterion="b", awarded=-1, max_points=5, justification=""),
        ],
        misconceptions_observed=[], feedback="",
    )
    assert g.score() == 0.5


# --- graph ---------------------------------------------------------------------------

def test_sanitize_drops_unknown_prereqs_cycles_and_bad_levels():
    g = sanitize(graph(
        skill("A", prereqs=["b", "ghost"], levels=[9, 0]),
        skill("b", prereqs=["a"]),
    ))
    ids = {s.id for s in g.skills}
    assert ids == {"a", "b"}
    a, b = g.skills
    assert "ghost" not in a.prerequisites
    assert not (b.id in a.prerequisites and a.id in b.prerequisites)  # cycle broken
    assert a.required_levels == [1, 7]
    order = topo_order(g)
    for s in g.skills:
        for p in s.prerequisites:
            assert order.index(p) < order.index(s.id)


def test_sanitize_dedupes_ids():
    g = sanitize(graph(skill("x"), skill("x")))
    assert [s.id for s in g.skills] == ["x", "x_2"]


# --- scheduler -----------------------------------------------------------------------

def test_review_schedule_expands_and_resets():
    st = SkillState("s")
    scheduler.on_mastered(st, now=0)
    assert st.review_due_at == scheduler.DAY
    scheduler.on_review(st, True, now=scheduler.DAY)
    assert st.review_due_at == scheduler.DAY + 3 * scheduler.DAY
    scheduler.on_review(st, False, now=10 * scheduler.DAY)
    assert st.review_stage == 0


# --- policy --------------------------------------------------------------------------

def _act(g, states, capstone=False, now=0.0):
    return next_action(g, states, capstone_passed=capstone, now=now, mastery_p=0.95, prereq_p=0.8)


def test_policy_respects_prerequisites_and_teaches_novices_first():
    g = sanitize(graph(skill("adv", prereqs=["base"]), skill("base")))
    states = {"adv": SkillState("adv"), "base": SkillState("base")}
    a = _act(g, states)
    assert (a.kind, a.skill_id, a.level) == ("teach", "base", 2)


def test_policy_lets_confident_learner_test_out():
    g = sanitize(graph(skill("base")))
    a = _act(g, {"base": SkillState("base", p_known=0.6)})
    assert a.kind == "assess"


def test_policy_assesses_after_teaching():
    g = sanitize(graph(skill("base")))
    a = _act(g, {"base": SkillState("base", pending_assessment=True)})
    assert a.kind == "assess"


def test_policy_capstone_then_done_then_reviews():
    g = sanitize(graph(skill("base")))
    st = SkillState("base", p_known=0.99, passed_levels=[2, 3])
    assert _act(g, {"base": st}).kind == "capstone"
    assert _act(g, {"base": st}, capstone=True).kind == "done"
    scheduler.on_mastered(st, now=0)
    a = _act(g, {"base": st}, capstone=True, now=2 * scheduler.DAY)
    assert (a.kind, a.level) == ("review", 3)
