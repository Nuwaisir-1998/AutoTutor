"""SQLite persistence for the learner profile, concepts, skill states, and items."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from autotutor.core.learner_model import SkillState
from autotutor.schemas import AssessmentItem, Grade, SkillGraph


@dataclass
class LearnerProfile:
    background: str
    goal: str
    venues: str


@dataclass
class Concept:
    id: int
    name: str
    graph: SkillGraph
    capstone_passed_at: float | None


@dataclass
class ItemRow:
    id: int
    concept_id: int
    skill_id: str | None
    kind: str
    batch: int | None
    item: AssessmentItem
    answer: str | None
    grade: Grade | None
    score: float | None
    passed: bool | None


class DB:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        schema = resources.files("autotutor.storage").joinpath("schema.sql").read_text()
        self.conn.executescript(schema)

    def close(self) -> None:
        self.conn.close()

    # --- learner -----------------------------------------------------------------

    def get_learner(self) -> LearnerProfile | None:
        row = self.conn.execute("SELECT * FROM learner WHERE id = 1").fetchone()
        if row is None:
            return None
        return LearnerProfile(row["background"], row["goal"], row["venues"])

    def save_learner(self, p: LearnerProfile) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO learner (id, background, goal, venues, created_at) VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET background=excluded.background, goal=excluded.goal, "
                "venues=excluded.venues",
                (p.background, p.goal, p.venues, time.time()),
            )

    # --- concepts ----------------------------------------------------------------

    def _concept(self, row: sqlite3.Row) -> Concept:
        return Concept(
            row["id"],
            row["name"],
            SkillGraph.model_validate_json(row["graph_json"]),
            row["capstone_passed_at"],
        )

    def get_concept(self, name: str) -> Concept | None:
        row = self.conn.execute("SELECT * FROM concept WHERE name = ?", (name,)).fetchone()
        return self._concept(row) if row else None

    def get_concept_by_id(self, concept_id: int) -> Concept:
        row = self.conn.execute("SELECT * FROM concept WHERE id = ?", (concept_id,)).fetchone()
        return self._concept(row)

    def list_concepts(self) -> list[Concept]:
        rows = self.conn.execute("SELECT * FROM concept ORDER BY created_at").fetchall()
        return [self._concept(r) for r in rows]

    def create_concept(self, name: str, graph: SkillGraph) -> Concept:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO concept (name, graph_json, created_at) VALUES (?, ?, ?)",
                (name, graph.model_dump_json(), time.time()),
            )
            cid = cur.lastrowid
            for skill in graph.skills:
                self._write_state(cid, SkillState(skill.id))
        return Concept(cid, name, graph, None)

    def delete_concept(self, name: str) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM concept WHERE name = ?", (name,))
        return cur.rowcount > 0

    def set_capstone_passed(self, concept_id: int, when: float | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE concept SET capstone_passed_at = ? WHERE id = ?", (when, concept_id)
            )

    # --- skill state -------------------------------------------------------------

    def get_states(self, concept_id: int) -> dict[str, SkillState]:
        rows = self.conn.execute(
            "SELECT * FROM skill_state WHERE concept_id = ?", (concept_id,)
        ).fetchall()
        return {
            r["skill_id"]: SkillState(
                skill_id=r["skill_id"],
                p_known=r["p_known"],
                passed_levels=json.loads(r["passed_levels"]),
                attempts=r["attempts"],
                pending_assessment=bool(r["pending_assessment"]),
                misconceptions=json.loads(r["misconceptions"]),
                mastered_at=r["mastered_at"],
                review_stage=r["review_stage"],
                review_due_at=r["review_due_at"],
            )
            for r in rows
        }

    def save_state(self, concept_id: int, st: SkillState) -> None:
        with self.conn:
            self._write_state(concept_id, st)

    def _write_state(self, concept_id: int, st: SkillState) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO skill_state (concept_id, skill_id, p_known, passed_levels, "
            "attempts, pending_assessment, misconceptions, mastered_at, review_stage, review_due_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                concept_id, st.skill_id, st.p_known, json.dumps(st.passed_levels), st.attempts,
                int(st.pending_assessment), json.dumps(st.misconceptions), st.mastered_at,
                st.review_stage, st.review_due_at,
            ),
        )

    # --- items -------------------------------------------------------------------

    def _item(self, r: sqlite3.Row) -> ItemRow:
        return ItemRow(
            id=r["id"],
            concept_id=r["concept_id"],
            skill_id=r["skill_id"],
            kind=r["kind"],
            batch=r["batch"],
            item=AssessmentItem.model_validate_json(r["item_json"]),
            answer=r["answer"],
            grade=Grade.model_validate_json(r["grade_json"]) if r["grade_json"] else None,
            score=r["score"],
            passed=None if r["passed"] is None else bool(r["passed"]),
        )

    def add_item(
        self, concept_id: int, skill_id: str | None, kind: str, item: AssessmentItem,
        batch: int | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO item (concept_id, skill_id, kind, batch, bloom_level, item_json, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (concept_id, skill_id, kind, batch, item.bloom_level, item.model_dump_json(),
                 time.time()),
            )
        return cur.lastrowid

    def next_batch(self, concept_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(batch), 0) + 1 AS b FROM item WHERE concept_id = ?", (concept_id,)
        ).fetchone()
        return row["b"]

    def get_item(self, item_id: int) -> ItemRow | None:
        row = self.conn.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone()
        return self._item(row) if row else None

    def open_items(self, concept_id: int) -> list[ItemRow]:
        rows = self.conn.execute(
            "SELECT * FROM item WHERE concept_id = ? AND grade_json IS NULL ORDER BY id",
            (concept_id,),
        ).fetchall()
        return [self._item(r) for r in rows]

    def batch_items(self, concept_id: int, batch: int) -> list[ItemRow]:
        rows = self.conn.execute(
            "SELECT * FROM item WHERE concept_id = ? AND batch = ? ORDER BY id", (concept_id, batch)
        ).fetchall()
        return [self._item(r) for r in rows]

    def set_answer(self, item_id: int, answer: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE item SET answer = ? WHERE id = ?", (answer, item_id))

    def set_grade(self, item_id: int, grade: Grade, score: float, passed: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE item SET grade_json = ?, score = ?, passed = ?, graded_at = ? WHERE id = ?",
                (grade.model_dump_json(), score, int(passed), time.time(), item_id),
            )

    def recent_item_prompts(self, concept_id: int, skill_id: str | None, limit: int = 8) -> list[str]:
        """Prompts already asked, so the examiner doesn't repeat itself."""
        rows = self.conn.execute(
            "SELECT item_json FROM item WHERE concept_id = ? AND skill_id IS ? "
            "ORDER BY id DESC LIMIT ?",
            (concept_id, skill_id, limit),
        ).fetchall()
        return [AssessmentItem.model_validate_json(r["item_json"]).prompt for r in rows]

    def last_feedback(self, concept_id: int, skill_id: str) -> str:
        """Most recent grader feedback that touched this skill (incl. capstone items)."""
        rows = self.conn.execute(
            "SELECT skill_id, item_json, grade_json FROM item WHERE concept_id = ? "
            "AND grade_json IS NOT NULL ORDER BY graded_at DESC LIMIT 20",
            (concept_id,),
        ).fetchall()
        for r in rows:
            tested = AssessmentItem.model_validate_json(r["item_json"]).skills_tested
            if r["skill_id"] == skill_id or skill_id in tested:
                return Grade.model_validate_json(r["grade_json"]).feedback
        return ""
