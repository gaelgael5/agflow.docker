-- Table unique enregistrant le runtime container détecté sur la machine.
-- Écrite une seule fois (première détection), validée à chaque démarrage.
CREATE TABLE IF NOT EXISTS runtime_config (
    id           SERIAL PRIMARY KEY,
    mode         VARCHAR(32) NOT NULL,
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
