-- 015_agent_skills — N-N binding between agents and skills catalog
CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id  UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill_id  UUID NOT NULL REFERENCES skills(id) ON DELETE RESTRICT,
    position  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_skills_agent ON agent_skills(agent_id, position);
