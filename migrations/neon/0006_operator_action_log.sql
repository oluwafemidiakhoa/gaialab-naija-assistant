-- GaiaLab Naija Trust Rail / operator action audit ledger
-- Migration: 0006_operator_action_log

CREATE TABLE IF NOT EXISTS operator_action_log_heads (
    stream_id TEXT PRIMARY KEY,
    last_action_hash TEXT NOT NULL
);

INSERT INTO operator_action_log_heads (stream_id, last_action_hash)
VALUES ('global', repeat('0', 64))
ON CONFLICT (stream_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS operator_actions (
    event_id BIGSERIAL PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE,
    operator_id TEXT NOT NULL,
    key_id TEXT,
    action_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id_sha256 TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    previous_action_hash TEXT NOT NULL,
    action_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_operator_actions_operator
    ON operator_actions(operator_id, event_id);

CREATE INDEX IF NOT EXISTS idx_operator_actions_target
    ON operator_actions(target_type, target_id_sha256, event_id);

REVOKE ALL ON TABLE operator_action_log_heads FROM PUBLIC;
REVOKE ALL ON TABLE operator_actions FROM PUBLIC;
