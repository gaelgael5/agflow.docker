-- Étend users_role_check pour inclure operator et viewer (nécessaire pour l'auth Keycloak)
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role = ANY (ARRAY['admin', 'user', 'operator', 'viewer']));
