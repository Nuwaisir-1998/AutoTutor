"""Pydantic models used as structured-output schemas for the LLM roles.

Keep these free of numeric/length constraints: structured outputs enforce the shape,
and code (not the schema) enforces ranges after parsing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Misconception(BaseModel):
    id: str  # stable snake_case id, e.g. "attention_scaling_is_for_speed"
    description: str


class Skill(BaseModel):
    id: str  # snake_case, unique within the concept
    name: str
    description: str
    prerequisites: list[str]  # ids of other skills in this graph
    required_levels: list[int]  # Bloom ladder levels (1-7) the learner must pass
    key_ideas: list[str]
    common_misconceptions: list[Misconception]
    key_papers: list[str]  # "Authors (Year). Title. Venue."


class SkillGraph(BaseModel):
    concept: str
    summary: str
    skills: list[Skill]
    research_frontier: list[str]  # open problems a researcher should know about


ItemType = Literal[
    "short_answer",
    "explain",
    "derivation",
    "code",
    "analysis",
    "paper_critique",
    "experiment_design",
    "research_proposal",
]


class RubricCriterion(BaseModel):
    criterion: str
    points: int


class AssessmentItem(BaseModel):
    prompt: str  # what the learner sees (markdown)
    item_type: ItemType
    bloom_level: int
    skills_tested: list[str]
    rubric: list[RubricCriterion]
    reference_answer: str
    targeted_misconceptions: list[str]  # misconception ids this item is designed to expose


class CapstoneExam(BaseModel):
    items: list[AssessmentItem]


class CriterionScore(BaseModel):
    criterion: str
    awarded: int
    max_points: int
    justification: str


class Grade(BaseModel):
    criterion_scores: list[CriterionScore]
    misconceptions_observed: list[Misconception]
    feedback: str  # addressed to the learner

    def score(self) -> float:
        total = sum(max(0, c.max_points) for c in self.criterion_scores)
        if total == 0:
            return 0.0
        got = sum(min(max(0, c.awarded), max(0, c.max_points)) for c in self.criterion_scores)
        return got / total
