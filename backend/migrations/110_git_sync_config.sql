-- 110_git_sync_config.sql — Configuration singleton de la synchronisation Git

CREATE TABLE git_sync_config (
    id                        int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    repo_url                  text NOT NULL,
    auth_mode                 text NOT NULL CHECK (auth_mode IN ('ssh_key', 'pat_https', 'basic_https')),
    auth_secret_ref           text NOT NULL,
    branch                    text NOT NULL DEFAULT 'main',
    commit_author_name        text NOT NULL DEFAULT 'agflow bot',
    commit_author_email       text NOT NULL DEFAULT 'bot@agflow.local',
    excluded_columns          jsonb NOT NULL DEFAULT '{}'::jsonb,
    selected_tables           jsonb NOT NULL DEFAULT '[]'::jsonb,
    cron_expr                 text,
    cron_enabled              boolean NOT NULL DEFAULT false,
    last_export_at            timestamptz,
    last_export_status        text CHECK (last_export_status IN ('ok', 'failed')),
    last_export_sha           text,
    last_export_error         text,
    last_export_tables_count  int,
    last_import_at            timestamptz,
    last_import_status        text CHECK (last_import_status IN ('ok', 'failed')),
    last_import_error         text,
    last_import_rows_inserted int,
    last_import_rows_updated  int,
    last_import_rows_deleted  int,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_git_sync_config_updated_at') THEN
        CREATE TRIGGER trg_git_sync_config_updated_at
            BEFORE UPDATE ON git_sync_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
