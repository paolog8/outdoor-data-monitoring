-- Lookup tables for solar cell metadata

CREATE TABLE scientist (
    id          BIGSERIAL   PRIMARY KEY,
    name        TEXT        NOT NULL,
    affiliation TEXT        NOT NULL DEFAULT '',
    UNIQUE (name, affiliation)
);

CREATE TABLE project (
    id    BIGSERIAL   PRIMARY KEY,
    name  TEXT        NOT NULL UNIQUE
);

CREATE TABLE experiment (
    id    BIGSERIAL   PRIMARY KEY,
    name  TEXT        NOT NULL UNIQUE
);

-- Many-to-many: experiment ↔ project
CREATE TABLE experiment_project (
    experiment_id  BIGINT  NOT NULL REFERENCES experiment(id),
    project_id     BIGINT  NOT NULL REFERENCES project(id),
    PRIMARY KEY (experiment_id, project_id)
);
CREATE INDEX ON experiment_project (project_id);
