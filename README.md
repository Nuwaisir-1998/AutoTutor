# AutoTutor

An AI tutor that teaches a machine-learning concept until you reach **research-grade mastery**, meaning you could build on the concept in a paper accepted at NeurIPS, ICML, ICLR, JMLR or TPAMI, and review someone else's paper on it.

AutoTutor runs **inside Claude Code** on your Claude subscription. It needs no API key.

## Setup (once)

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

## Use

Open Claude Code in this folder and type:

```
/autotutor self-attention       # start or resume a concept
/autotutor status               # mastery table
/autotutor review               # retention reviews that are due
```

You can stop at any point: everything is saved, and `/autotutor <concept>` resumes exactly where you left off. To change the default learner profile:

```
.venv/bin/autotutor profile --background "..." --goal "..." --venues "..."
```

## How it works

| Part | What it is | Role |
|---|---|---|
| **Tutor** | the Claude Code conversation, using [.claude/skills/autotutor/SKILL.md](.claude/skills/autotutor/SKILL.md) | Teaches by asking questions, and makes you do the work at the target level. |
| **Planner** | subagent, [.claude/agents/autotutor-planner.md](.claude/agents/autotutor-planner.md) | Turns the concept into a prerequisite graph of skills and research-practice skills. |
| **Examiner** | subagent, [.claude/agents/autotutor-examiner.md](.claude/agents/autotutor-examiner.md) | Writes new questions with rubrics. It never sees the tutoring, and returns only item ids. |
| **Grader** | subagent, [.claude/agents/autotutor-grader.md](.claude/agents/autotutor-grader.md) | Scores answers strictly against the rubric. |
| **`autotutor` CLI** | Python, [autotutor/](autotutor/) | Stores all state (SQLite at `~/.autotutor/autotutor.db`), tracks mastery, and decides what comes next. |

The subagents work in their own contexts, so the examiner and grader stay independent of the tutor. The CLI shows the learner only the question text. Rubrics and reference answers go only to the grader.

## What "mastered" means

1. **Every skill passes at every Bloom level it requires.** The ladder is designed for research: L1 recall, L2 explain, L3 derive, L4 implement, L5 analyze, L6 critique (reviewing a fictional paper with planted flaws) and L7 create (experiment design or a research proposal).
2. **A Bayesian Knowledge Tracing estimate of P(known) is at least 0.95** for every skill.
3. **You pass a capstone exam** of new, integrative items.
4. **You pass retention reviews 1, 3 and 7 days later.** If you fail one, the skill goes back to teaching, and you have to pass the capstone again.

Thresholds can be changed with `AUTOTUTOR_PASS_SCORE` (0.8), `AUTOTUTOR_MASTERY_P` (0.95), `AUTOTUTOR_PREREQ_P` (0.8) and `AUTOTUTOR_DB`.

## Tests

```bash
.venv/bin/pytest
```
