# Migration infra_machines.password → Harpocrate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le chiffrement Fernet (`AGFLOW_INFRA_KEY`) du mot de passe des machines par un stockage dans Harpocrate vault. La colonne `password` contiendra une référence de type `${vault://HARPOCRATE_KEY:machines/<uuid>/password}` au lieu d'un token Fernet.

**Architecture:** Chemin déterministe `machines/{uuid}/password` dans Harpocrate. `vault_client.py` existant (`create_secret / update_secret / delete_secret / get_secret`). Pas de migration de données (DB supprimée au prochain deploy). `metadata` reste JSONB non-chiffré (pas de données sensibles).

**Tech Stack:** asyncpg + `vault_client.py` (SDK Harpocrate async) + pytest

---

## File Structure

```
backend/src/agflow/services/
  infra_machines_service.py    MODIFY — remplacer crypto_service par vault_client
tests/services/
  test_infra_machines_vault.py CREATE — tests unitaires (vault mocké)
```

Pas de migration SQL — `password` est déjà `VARCHAR`, seul son contenu change.

---

## Task 1 : Helper vault ref + create() migré

**Files:**
- Modify: `backend/src/agflow/services/infra_machines_service.py`

- [ ] **Step 1 : Écrire le test rouge pour create()**

Dans `tests/services/test_infra_machines_vault.py` :

```python
from __future__ import annotations
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from agflow.services import infra_machines_service as svc


MACHINE_ID = uuid.uuid4()
TYPE_ID = uuid.uuid4()

_ROW = {
    "id": MACHINE_ID, "name": "test", "type_id": TYPE_ID,
    "type_name": "lxc", "category": "lxc",
    "host": "192.168.1.1", "port": 22, "username": "root",
    "password": f"${{vault://HARPOCRATE_KEY:machines/{MACHINE_ID}/password}}",
    "certificate_id": None, "parent_id": None, "user_id": None,
    "environment": None, "children_count": 0,
    "metadata": {}, "status": "not_initialized",
    "required_actions": [], "created_at": None, "updated_at": None,
}


@pytest.mark.asyncio
async def test_create_stores_vault_ref():
    """create() doit stocker un vault ref dans la colonne password."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        mock_vault.create_secret = AsyncMock(return_value="secret-id-123")
        # Premier fetch_one : INSERT RETURNING id
        mock_fetch.side_effect = [
            {"id": MACHINE_ID},  # INSERT RETURNING
            _ROW,                # get_by_id
        ]
        mock_exec.return_value = None  # UPDATE SET password

        result = await svc.create(
            type_id=TYPE_ID, host="192.168.1.1", password="s3cr3t"
        )

        # vault.create_secret appelé avec le bon chemin
        mock_vault.create_secret.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", "s3cr3t"
        )
        # execute appelé pour mettre à jour la colonne password avec le vault ref
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert f"machines/{MACHINE_ID}/password" in call_args[1]
        assert result.has_password is True
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

```bash
cd backend && uv run pytest tests/services/test_infra_machines_vault.py::test_create_stores_vault_ref -v
```

Attendu : FAILED (ImportError ou AttributeError — vault_client pas encore importé).

- [ ] **Step 3 : Ajouter le helper vault ref et modifier create()**

Dans `infra_machines_service.py`, remplacer l'import `crypto_service` et ajouter :

```python
import re
import uuid as _uuid
from agflow.services import vault_client

_VAULT_REF_RE = re.compile(r"^\$\{vault://([^:]+):(.+)\}$")


def _vault_path(machine_id: _uuid.UUID) -> str:
    return f"machines/{machine_id}/password"


def _vault_ref(machine_id: _uuid.UUID) -> str:
    return f"${{vault://HARPOCRATE_KEY:{_vault_path(machine_id)}}}"


def _parse_vault_ref(value: str | None) -> str | None:
    """Retourne le chemin vault si value est un vault ref, sinon None."""
    if not value:
        return None
    m = _VAULT_REF_RE.match(value)
    return m.group(2) if m else None
```

Modifier `create()` :

```python
async def create(
    type_id: _uuid.UUID,
    host: str,
    port: int = 22,
    username: str | None = None,
    password: str | None = None,
    certificate_id: _uuid.UUID | None = None,
    name: str = "",
    metadata: dict | None = None,
    parent_id: _uuid.UUID | None = None,
    user_id: _uuid.UUID | None = None,
    environment: str | None = None,
) -> MachineSummary:
    # INSERT sans password — on récupère l'UUID généré par Postgres
    row = await fetch_one(
        """
        INSERT INTO infra_machines
            (name, type_id, host, port, username,
             certificate_id, parent_id, metadata, user_id, environment)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $9::jsonb, $10, $11)
        RETURNING id
        """,
        name, type_id, host, port, username,
        certificate_id, parent_id,
        _json.dumps(metadata or {}),
        user_id, environment,
    )
    assert row is not None
    machine_id: _uuid.UUID = row["id"]

    # Stocker le password dans Harpocrate, puis écrire le vault ref en DB
    if password is not None:
        try:
            await vault_client.create_secret(_vault_path(machine_id), password)
            await execute(
                "UPDATE infra_machines SET password = $1 WHERE id = $2",
                _vault_ref(machine_id), machine_id,
            )
        except Exception:
            # Rollback : supprimer la machine si le vault échoue
            await execute("DELETE FROM infra_machines WHERE id = $1", machine_id)
            raise

    _log.info("infra_machines.create", host=host, type_id=str(type_id))
    return await get_by_id(machine_id)
```

⚠ Corriger le numérotation des `$N` dans l'INSERT (les paramètres doivent être consécutifs sans trou).

- [ ] **Step 4 : Vérifier que le test passe**

```bash
cd backend && uv run pytest tests/services/test_infra_machines_vault.py::test_create_stores_vault_ref -v
```

Attendu : PASSED.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/infra_machines_service.py \
        backend/tests/services/test_infra_machines_vault.py
git commit -m "feat(machines): create() stocke password dans Harpocrate"
```

---

## Task 2 : get_credentials() migré

**Files:**
- Modify: `backend/src/agflow/services/infra_machines_service.py`
- Modify: `tests/services/test_infra_machines_vault.py`

- [ ] **Step 1 : Écrire le test rouge**

```python
@pytest.mark.asyncio
async def test_get_credentials_reads_from_vault():
    """get_credentials() doit lire le password depuis Harpocrate."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
    ):
        mock_vault.get_secret = AsyncMock(return_value="s3cr3t")
        mock_fetch.return_value = {
            "host": "192.168.1.1", "port": 22, "username": "root",
            "password": f"${{vault://HARPOCRATE_KEY:machines/{MACHINE_ID}/password}}",
            "certificate_id": None,
        }

        creds = await svc.get_credentials(MACHINE_ID)

        mock_vault.get_secret.assert_called_once_with(
            f"machines/{MACHINE_ID}/password"
        )
        assert creds["password"] == "s3cr3t"


@pytest.mark.asyncio
async def test_get_credentials_no_password():
    """get_credentials() retourne None si pas de vault ref."""
    with patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "host": "192.168.1.1", "port": 22, "username": "root",
            "password": None, "certificate_id": None,
        }
        creds = await svc.get_credentials(MACHINE_ID)
        assert creds["password"] is None
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_infra_machines_vault.py::test_get_credentials_reads_from_vault -v
```

Attendu : FAILED.

- [ ] **Step 3 : Modifier get_credentials()**

```python
async def get_credentials(machine_id: _uuid.UUID) -> dict[str, Any]:
    """Return credentials for SSH use. Password fetched from Harpocrate."""
    row = await fetch_one(
        "SELECT host, port, username, password, certificate_id FROM infra_machines WHERE id = $1",
        machine_id,
    )
    if row is None:
        raise MachineNotFoundError(f"Machine {machine_id} not found")

    plain_password: str | None = None
    path = _parse_vault_ref(row["password"])
    if path:
        plain_password = await vault_client.get_secret(path)

    return {
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "password": plain_password,
        "certificate_id": row.get("certificate_id"),
    }
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_infra_machines_vault.py -v
```

Attendu : 3 PASSED.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/infra_machines_service.py \
        backend/tests/services/test_infra_machines_vault.py
git commit -m "feat(machines): get_credentials() lit depuis Harpocrate"
```

---

## Task 3 : update() et delete() migrés

**Files:**
- Modify: `backend/src/agflow/services/infra_machines_service.py`
- Modify: `tests/services/test_infra_machines_vault.py`

- [ ] **Step 1 : Écrire les tests rouges**

```python
@pytest.mark.asyncio
async def test_update_password_calls_update_secret_when_path_exists():
    """update() avec password existant → vault.update_secret, pas de UPDATE DB."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
        patch("agflow.services.infra_machines_service.fetch_all") as mock_all,
    ):
        vault_ref = f"${{vault://HARPOCRATE_KEY:machines/{MACHINE_ID}/password}}"
        mock_vault.update_secret = AsyncMock()
        # get_by_id (check existence) + SELECT password + get_by_id (return)
        mock_fetch.side_effect = [_ROW, {"password": vault_ref}, _ROW]
        mock_exec.return_value = None

        await svc.update(MACHINE_ID, password="new_secret")

        mock_vault.update_secret.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", "new_secret"
        )


@pytest.mark.asyncio
async def test_update_password_calls_create_secret_when_no_path():
    """update() avec password absent en DB → vault.create_secret + UPDATE DB."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        mock_vault.create_secret = AsyncMock(return_value="secret-id")
        no_pw_row = {**_ROW, "password": None}
        mock_fetch.side_effect = [no_pw_row, {"password": None}, _ROW]
        mock_exec.return_value = None

        await svc.update(MACHINE_ID, password="new_secret")

        mock_vault.create_secret.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", "new_secret"
        )


@pytest.mark.asyncio
async def test_delete_removes_vault_secret():
    """delete() doit supprimer le secret dans Harpocrate avant la machine en DB."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
    ):
        vault_ref = f"${{vault://HARPOCRATE_KEY:machines/{MACHINE_ID}/password}}"
        mock_vault.delete_secret = AsyncMock()
        # SELECT password + DELETE RETURNING id
        mock_fetch.side_effect = [
            {"password": vault_ref},
            {"id": MACHINE_ID},
        ]

        await svc.delete(MACHINE_ID)

        mock_vault.delete_secret.assert_called_once_with(
            f"machines/{MACHINE_ID}/password"
        )
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_infra_machines_vault.py -k "update or delete" -v
```

Attendu : FAILED.

- [ ] **Step 3 : Modifier update()**

```python
async def update(machine_id: _uuid.UUID, **kwargs: Any) -> MachineSummary:
    await get_by_id(machine_id)

    # Gérer le password séparément (vault)
    new_password: str | None = kwargs.pop("password", None)
    if new_password is not None:
        pw_row = await fetch_one(
            "SELECT password FROM infra_machines WHERE id = $1", machine_id
        )
        existing_path = _parse_vault_ref(pw_row["password"] if pw_row else None)
        if existing_path:
            await vault_client.update_secret(existing_path, new_password)
        else:
            await vault_client.create_secret(_vault_path(machine_id), new_password)
            await execute(
                "UPDATE infra_machines SET password = $1 WHERE id = $2",
                _vault_ref(machine_id), machine_id,
            )

    # Autres champs (sans password)
    updates: dict[str, Any] = {}
    for field in ("name", "host", "port", "username", "certificate_id", "user_id", "environment"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]

    if updates:
        sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
        await execute(
            f"UPDATE infra_machines SET {', '.join(sets)} WHERE id = $1",
            machine_id, *updates.values(),
        )

    _log.info("infra_machines.update", id=str(machine_id))
    return await get_by_id(machine_id)
```

- [ ] **Step 4 : Modifier delete()**

```python
async def delete(machine_id: _uuid.UUID) -> None:
    # Lire le vault ref AVANT de supprimer
    pw_row = await fetch_one(
        "SELECT password FROM infra_machines WHERE id = $1", machine_id
    )
    path = _parse_vault_ref(pw_row["password"] if pw_row else None)

    row = await fetch_one(
        "DELETE FROM infra_machines WHERE id = $1 RETURNING id", machine_id
    )
    if row is None:
        raise MachineNotFoundError(f"Machine {machine_id} not found")

    if path:
        try:
            await vault_client.delete_secret(path)
        except Exception:
            _log.warning("infra_machines.vault_delete_failed", id=str(machine_id), path=path)

    _log.info("infra_machines.delete", id=str(machine_id))
```

- [ ] **Step 5 : Vérifier tous les tests**

```bash
cd backend && uv run pytest tests/services/test_infra_machines_vault.py -v
```

Attendu : 6 PASSED.

- [ ] **Step 6 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/infra_machines_service.py
```

Attendu : All checks passed.

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/infra_machines_service.py \
        backend/tests/services/test_infra_machines_vault.py
git commit -m "feat(machines): update() + delete() migrent password vers Harpocrate"
```

---

## Task 4 : Supprimer crypto_service des machines + vérification finale

**Files:**
- Modify: `backend/src/agflow/services/infra_machines_service.py`

- [ ] **Step 1 : Retirer l'import crypto_service**

Supprimer :
```python
from agflow.services import crypto_service
```

Vérifier qu'aucun appel `crypto_service.*` ne reste dans le fichier.

- [ ] **Step 2 : Vérifier que crypto_service n'est plus utilisé par ce module**

```bash
cd backend && grep -n "crypto_service" src/agflow/services/infra_machines_service.py
```

Attendu : aucun résultat.

- [ ] **Step 3 : Lancer tous les tests**

```bash
cd backend && uv run pytest tests/services/test_infra_machines_vault.py -v
```

Attendu : 6 PASSED.

- [ ] **Step 4 : Lint final**

```bash
cd backend && uv run ruff check src/agflow/services/infra_machines_service.py
```

- [ ] **Step 5 : Commit final**

```bash
git add backend/src/agflow/services/infra_machines_service.py
git commit -m "chore(machines): supprimer import crypto_service (password → Harpocrate)"
```

---

## Checklist de validation finale

- [ ] `grep -r "crypto_service" src/agflow/services/infra_machines_service.py` → vide
- [ ] `create()` ne passe plus jamais de Fernet token à Postgres
- [ ] `get_credentials()` lit depuis Harpocrate (jamais `crypto_service.decrypt`)
- [ ] `update()` appelle `update_secret` si vault ref déjà en DB, `create_secret` sinon
- [ ] `delete()` supprime le secret vault avant la ligne DB (best-effort, log si échec)
- [ ] `has_password` dans `_to_summary` reste `bool(row.get("password"))` — fonctionne car vault ref est truthy
- [ ] `metadata` JSONB non touché
- [ ] `AGFLOW_INFRA_KEY` toujours dans `.env` (encore utilisé par `infra_certificates`)
- [ ] 6 tests unitaires passent avec vault mocké
