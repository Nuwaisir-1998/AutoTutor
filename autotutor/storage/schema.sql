CREATE TABLE IF NOT EXISTS learner (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    background  TEXT NOT NULL,
    goal        TEXT NOT NULL,
    venues      TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS concept (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE COLLATE NOCASE,
    graph_json          TEXT NOT NULL,
    capstone_passed_at  REAL,
    created_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_state (
    concept_id          INTEGER NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
    skill_id            TEXT NOT NULL,
    p_known             REAL NOT NULL,
    passed_levels       TEXT NOT NULL,   -- JSON list[int]
    attempts            INTEGER NOT NULL,
    pending_assessment  INTEGER NOT NULL,
    misconceptions      TEXT NOT NULL,   -- JSON {id: description}
    mastered_at         REAL,
    review_stage        INTEGER NOT NULL,
    review_due_at       REAL,
    PRIMARY KEY (concept_id, skill_id)
);

-- One row per assessment item: written by the examiner, answered by the learner,
-- scored by the grader. Rows with grade_json IS NULL are still open.
CREATE TABLE IF NOT EXISTS item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id  INTEGER NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
    skill_id    TEXT,                    -- NULL for capstone items
    kind        TEXT NOT NULL,           -- assess | review | capstone
    batch       INTEGER,                 -- groups the items of one capstone exam
    bloom_level INTEGER NOT NULL,
    item_json   TEXT NOT NULL,
    answer      TEXT,
    grade_json  TEXT,
    score       REAL,
    passed      INTEGER,
    created_at  REAL NOT NULL,
    graded_at   REAL
);

CREATE INDEX IF NOT EXISTS item_by_skill ON item(concept_id, skill_id);
