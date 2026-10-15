"""State and curriculum CLI that Claude Code drives (no API key needed).

Claude Code acts as the tutor and runs the planner/examiner/grader subagents; this
tool stores everything and decides what happens next. JSON payloads are read from
stdin. Run `autotutor <command> -h` for details.
"""

from __future__ import annotations

import argparse
import json
import sys

from autotutor import service
from autotutor.config import CONFIG
from autotutor.service import UserError
from autotutor.storage.db import DB, LearnerProfile


def _out(obj: object) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False))


def _stdin() -> str:
    data = sys.stdin.read()
    if not data.strip():
        raise UserError("Expected input on stdin.")
    return data


def cmd_profile(db: DB, a: argparse.Namespace) -> None:
    p = service.profile(db)
    if a.background or a.goal or a.venues:
        p = LearnerProfile(a.background or p.background, a.goal or p.goal, a.venues or p.venues)
        db.save_learner(p)
    _out(p.__dict__)


def cmd_next(db: DB, a: argparse.Namespace) -> None:
    _out(service.next_step(db, a.concept, CONFIG))


def cmd_create(db: DB, a: argparse.Namespace) -> None:
    c = service.create_concept(db, a.concept, _stdin())
    _out(service.graph_text(c))


def cmd_rate(db: DB, a: argparse.Namespace) -> None:
    ratings = {}
    for pair in a.ratings:
        sid, _, r = pair.partition("=")
        if not r.isdigit():
            raise UserError(f"Bad rating {pair!r}; use skill_id=0..3")
        ratings[sid] = int(r)
    service.rate(db, service.require_concept(db, a.concept), ratings)
    _out("Ratings saved.")


def cmd_tutor_brief(db: DB, a: argparse.Namespace) -> None:
    _out(service.tutor_brief(db, service.require_concept(db, a.concept), a.skill, a.level))


def cmd_taught(db: DB, a: argparse.Namespace) -> None:
    service.mark_taught(db, service.require_concept(db, a.concept), a.skill)
    _out("Marked ready for assessment.")


def cmd_examiner_brief(db: DB, a: argparse.Namespace) -> None:
    c = service.require_concept(db, a.concept)
    _out(service.examiner_brief(db, c, a.kind, a.skill, a.level))


def cmd_add_item(db: DB, a: argparse.Namespace) -> None:
    c = service.require_concept(db, a.concept)
    ids = service.add_items(db, c, a.kind, a.skill, a.level, _stdin())
    _out({"item_ids": ids})


def cmd_show_item(db: DB, a: argparse.Namespace) -> None:
    _out(service.learner_view(db, service.require_item(db, a.item_id)))


def cmd_answer(db: DB, a: argparse.Namespace) -> None:
    service.submit_answer(db, service.require_item(db, a.item_id), sys.stdin.read())
    _out(f"Answer to item #{a.item_id} saved. Next: have the autotutor-grader grade it.")


def cmd_grading_packet(db: DB, a: argparse.Namespace) -> None:
    _out(service.grading_packet(db, service.require_item(db, a.item_id)))


def cmd_grade(db: DB, a: argparse.Namespace) -> None:
    _out(service.submit_grade(db, service.require_item(db, a.item_id), _stdin(), CONFIG))


def cmd_status(db: DB, a: argparse.Namespace) -> None:
    names = [a.concept] if a.concept else [c.name for c in db.list_concepts()]
    if not names:
        _out("No concepts yet.")
    for name in names:
        _out(service.status_text(db, service.require_concept(db, name), CONFIG))


def cmd_graph(db: DB, a: argparse.Namespace) -> None:
    _out(service.graph_text(service.require_concept(db, a.concept)))


def cmd_due(db: DB, a: argparse.Namespace) -> None:
    _out({"concepts_with_reviews_due": service.due_concepts(db)})


def cmd_schema(db: DB, a: argparse.Namespace) -> None:
    _out(service.schema_json(a.name))


def cmd_reset(db: DB, a: argparse.Namespace) -> None:
    if not a.yes:
        raise UserError("This deletes all progress on the concept; re-run with --yes.")
    _out("Deleted." if db.delete_concept(a.concept) else "Unknown concept.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autotutor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, fn, help: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(fn=fn)
        return sp

    sp = add("profile", cmd_profile, "show or update the learner profile")
    sp.add_argument("--background"); sp.add_argument("--goal"); sp.add_argument("--venues")

    add("next", cmd_next, "what to do next for a concept (JSON)").add_argument("concept")
    add("create", cmd_create, "store a planned concept (SkillGraph JSON on stdin)").add_argument("concept")

    sp = add("rate", cmd_rate, "seed priors from self-ratings: skill_id=0..3 ...")
    sp.add_argument("concept"); sp.add_argument("ratings", nargs="+")

    sp = add("tutor-brief", cmd_tutor_brief, "context for teaching one skill")
    sp.add_argument("concept"); sp.add_argument("skill"); sp.add_argument("level", type=int)

    sp = add("taught", cmd_taught, "mark a teaching episode finished")
    sp.add_argument("concept"); sp.add_argument("skill")

    for name, fn, help in [
        ("examiner-brief", cmd_examiner_brief, "context for writing items (JSON)"),
        ("add-item", cmd_add_item, "store item(s): AssessmentItem or CapstoneExam JSON on stdin"),
    ]:
        sp = add(name, fn, help)
        sp.add_argument("concept")
        sp.add_argument("--kind", choices=["assess", "review", "capstone"], required=True)
        sp.add_argument("--skill"); sp.add_argument("--level", type=int)

    add("show-item", cmd_show_item, "learner-facing question text").add_argument("item_id", type=int)
    add("answer", cmd_answer, "store the learner's answer (stdin)").add_argument("item_id", type=int)
    add("grading-packet", cmd_grading_packet, "rubric + answer for the grader (JSON)").add_argument("item_id", type=int)
    add("grade", cmd_grade, "submit Grade JSON on stdin; updates mastery").add_argument("item_id", type=int)

    add("status", cmd_status, "mastery table").add_argument("concept", nargs="?")
    add("graph", cmd_graph, "skill graph").add_argument("concept")
    add("due", cmd_due, "concepts with retention reviews due")
    add("schema", cmd_schema, "JSON schema: SkillGraph | AssessmentItem | CapstoneExam | Grade").add_argument("name")

    sp = add("reset", cmd_reset, "delete progress on a concept")
    sp.add_argument("concept"); sp.add_argument("--yes", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = DB(CONFIG.db_path)
    try:
        args.fn(db, args)
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
