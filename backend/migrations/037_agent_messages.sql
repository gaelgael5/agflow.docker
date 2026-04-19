-- 037_agent_messages.sql
-- MOM bus: message log + consumer group delivery tracking

CREATE TABLE IF NOT EXISTS agent_messages (
    msg_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_msg_id  UUID REFERENCES agent_messages(msg_id),
    v              INT  NOT NULL DEFAULT 1,
    session_id     TEXT NOT NULL,
    instance_id    TEXT NOT NULL,
    direction      TEXT NOT NULL CHECK (direction IN ('in','out')),
    kind           TEXT NOT NULL CHECK (kind IN ('instruction','cancel','event','result','error')),
    payload        JSONB NOT NULL,
    route          JSONB,
    source         TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_instance_dir_ts
    ON agent_messages (instance_id, direction, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_messages_session_ts
    ON agent_messages (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_messages_parent
    ON agent_messages (parent_msg_id) WHERE parent_msg_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_message_delivery (
    group_name    TEXT NOT NULL,
    msg_id        UUID NOT NULL REFERENCES agent_messages(msg_id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('pending','claimed','acked','failed')),
    claimed_at    TIMESTAMPTZ,
    claimed_by    TEXT,
    acked_at      TIMESTAMPTZ,
    retry_count   INT NOT NULL DEFAULT 0,
    last_error    TEXT,
    PRIMARY KEY (group_name, msg_id)
);

CREATE INDEX IF NOT EXISTS idx_delivery_group_pending
    ON agent_message_delivery (group_name, status, msg_id)
    WHERE status IN ('pending','claimed');
