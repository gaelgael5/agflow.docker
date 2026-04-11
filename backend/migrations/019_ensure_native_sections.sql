-- 019_ensure_native_sections — backfill missing native sections for roles
--
-- Migration 016 seeds natives for existing roles at its run time, but any
-- role inserted afterwards via a code path that bypasses
-- roles_service.create (raw SQL in tests, manual INSERT, import flows,
-- etc.) ends up without its 3 natives. This migration is a defensive
-- idempotent backfill that makes sure every role in the DB has its 3
-- natives. It is safe to re-run (ON CONFLICT DO NOTHING).

INSERT INTO role_sections (role_id, name, display_name, is_native, position)
SELECT r.id, 'roles', 'Rôles', TRUE, 0 FROM roles r
ON CONFLICT (role_id, name) DO NOTHING;

INSERT INTO role_sections (role_id, name, display_name, is_native, position)
SELECT r.id, 'missions', 'Missions', TRUE, 1 FROM roles r
ON CONFLICT (role_id, name) DO NOTHING;

INSERT INTO role_sections (role_id, name, display_name, is_native, position)
SELECT r.id, 'competences', 'Compétences', TRUE, 2 FROM roles r
ON CONFLICT (role_id, name) DO NOTHING;
