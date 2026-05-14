from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from sdk.git_sync.exceptions import GitCloneError, GitConflictError, GitPushError
from sdk.git_sync.git_service import GitService
from sdk.git_sync.models import AuthMode, GitConfig


def _make_config(repo_url: str, **overrides) -> GitConfig:
    defaults = dict(
        repo_url=repo_url,
        auth_mode=AuthMode.SSH_KEY,
        auth_secret_ref="dummy",
        module_name="docker",
        commit_author_name="agflow bot",
        commit_author_email="bot@example.org",
    )
    defaults.update(overrides)
    return GitConfig(**defaults)


def _patch_factory(fake_auth_provider):
    """Patche GitAuthProviderFactory.build pour court-circuiter la résolution vault."""
    async def _build(_config, _vault):
        return fake_auth_provider

    return patch(
        "sdk.git_sync.git_service.GitAuthProviderFactory.build",
        side_effect=_build,
    )


# ─── clone() ─────────────────────────────────────────────────────────────────


async def test_clone_clones_bare_repo_and_calls_provider_setup(
    bare_repo, fake_auth_provider, fake_vault
):
    config = _make_config(bare_repo)
    svc = GitService(config, fake_vault)

    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()

    try:
        assert repo_root.exists()
        assert (repo_root / ".git").exists()
        assert (repo_root / "README.md").exists()
        assert fake_auth_provider.setup_called == 1
    finally:
        svc.cleanup(repo_root)


async def test_clone_failure_raises_git_clone_error(
    fake_auth_provider, fake_vault, tmp_path
):
    bogus_url = (tmp_path / "does-not-exist").as_uri()
    config = _make_config(bogus_url)
    svc = GitService(config, fake_vault)

    with _patch_factory(fake_auth_provider), pytest.raises(GitCloneError):
        await svc.clone()


async def test_clone_checks_out_target_commit_when_set(
    bare_repo, fake_auth_provider, fake_vault, tmp_path
):
    """Si target_commit est défini, le clone est suivi d'un checkout dessus."""
    # On a besoin d'au moins 2 commits pour pouvoir tester le checkout sur un
    # SHA antérieur. On en ajoute un via un working clone temporaire.
    work = tmp_path / "work-add-commit"
    subprocess.run(
        ["git", "clone", bare_repo, str(work)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(work), "config", "user.email", "fixture@example.org"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "config", "user.name", "fixture"], check=True
    )
    initial_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (work / "new.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(work), "add", "new.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "add new.txt"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "main"],
        check=True,
        capture_output=True,
    )

    config = _make_config(bare_repo, target_commit=initial_sha)
    svc = GitService(config, fake_vault)

    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()

    try:
        # On a checkouté l'initial — new.txt ne doit pas être présent.
        assert (repo_root / "README.md").exists()
        assert not (repo_root / "new.txt").exists()
    finally:
        svc.cleanup(repo_root)


# ─── get_module_path() ───────────────────────────────────────────────────────


def test_get_module_path_creates_directories(tmp_path, fake_vault):
    config = _make_config("file:///dev/null", module_name="docker")
    svc = GitService(config, fake_vault)

    module_path = svc.get_module_path(tmp_path)

    assert module_path == tmp_path / "docker" / "datas"
    assert module_path.exists()
    assert module_path.is_dir()


# ─── pull_ff_only() ──────────────────────────────────────────────────────────


async def test_pull_ff_only_succeeds_when_up_to_date(
    bare_repo, fake_auth_provider, fake_vault
):
    config = _make_config(bare_repo)
    svc = GitService(config, fake_vault)
    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()
    try:
        # Aucun changement upstream → pull --ff-only OK.
        await svc.pull_ff_only(repo_root)
    finally:
        svc.cleanup(repo_root)


async def test_pull_ff_only_raises_conflict_when_local_diverges(
    bare_repo, fake_auth_provider, fake_vault, tmp_path
):
    config = _make_config(bare_repo)
    svc = GitService(config, fake_vault)
    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()
    try:
        # Crée un commit local divergent + un commit remote différent
        # → ff-only doit échouer.
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "user.email", "x@y.z"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "user.name", "x"], check=True
        )
        (repo_root / "local.txt").write_text("local")
        subprocess.run(
            ["git", "-C", str(repo_root), "add", "local.txt"], check=True
        )
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-m", "local"],
            check=True,
            capture_output=True,
        )

        # Pousse une divergence depuis un second working clone
        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", bare_repo, str(other)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(other), "config", "user.email", "z@y.x"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(other), "config", "user.name", "z"], check=True
        )
        (other / "remote.txt").write_text("remote")
        subprocess.run(["git", "-C", str(other), "add", "remote.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(other), "commit", "-m", "remote"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(other), "push", "origin", "main"],
            check=True,
            capture_output=True,
        )

        with pytest.raises(GitConflictError):
            await svc.pull_ff_only(repo_root)
    finally:
        svc.cleanup(repo_root)


# ─── commit_and_push() ───────────────────────────────────────────────────────


async def test_commit_and_push_returns_none_when_nothing_to_commit(
    bare_repo, fake_auth_provider, fake_vault
):
    config = _make_config(bare_repo)
    svc = GitService(config, fake_vault)
    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()
    try:
        sha = await svc.commit_and_push(repo_root, "msg")
        assert sha is None
    finally:
        svc.cleanup(repo_root)


async def test_commit_and_push_returns_sha_and_pushes(
    bare_repo, fake_auth_provider, fake_vault, tmp_path
):
    config = _make_config(bare_repo, module_name="docker")
    svc = GitService(config, fake_vault)
    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()
    try:
        module_path = svc.get_module_path(repo_root)
        (module_path / "data.csv").write_text("col\nval\n")
        sha = await svc.commit_and_push(repo_root, "feat: snapshot")
        assert sha is not None
        assert len(sha) == 40  # SHA-1 hex full

        # Vérifier que le push a bien atterri : on clone à nouveau et on
        # vérifie la présence du fichier.
        verify = tmp_path / "verify"
        subprocess.run(
            ["git", "clone", bare_repo, str(verify)],
            check=True,
            capture_output=True,
        )
        assert (verify / "docker" / "datas" / "data.csv").exists()
    finally:
        svc.cleanup(repo_root)


async def test_commit_and_push_uses_configured_author(
    bare_repo, fake_auth_provider, fake_vault, tmp_path
):
    config = _make_config(
        bare_repo,
        module_name="docker",
        commit_author_name="ag.flow bot",
        commit_author_email="bot@yoops.org",
    )
    svc = GitService(config, fake_vault)
    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()
    try:
        module_path = svc.get_module_path(repo_root)
        (module_path / "data.csv").write_text("a\n")
        await svc.commit_and_push(repo_root, "feat: snapshot")

        # Vérifie l'auteur du dernier commit
        log = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%an <%ae>"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert log == "ag.flow bot <bot@yoops.org>"
    finally:
        svc.cleanup(repo_root)


async def test_commit_and_push_raises_on_push_failure(
    bare_repo, fake_auth_provider, fake_vault, tmp_path
):
    """Si une divergence rend le push impossible, GitPushError."""
    config = _make_config(bare_repo)
    svc = GitService(config, fake_vault)
    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()
    try:
        # Crée un commit remote pour forcer une divergence non-ff
        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", bare_repo, str(other)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(other), "config", "user.email", "z@y.x"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(other), "config", "user.name", "z"], check=True
        )
        (other / "remote.txt").write_text("remote")
        subprocess.run(["git", "-C", str(other), "add", "remote.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(other), "commit", "-m", "remote"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(other), "push", "origin", "main"],
            check=True,
            capture_output=True,
        )

        # Maintenant commit local + push → doit échouer (non-ff)
        module_path = svc.get_module_path(repo_root)
        (module_path / "data.csv").write_text("local\n")
        with pytest.raises(GitPushError):
            await svc.commit_and_push(repo_root, "msg")
    finally:
        svc.cleanup(repo_root)


# ─── cleanup() ───────────────────────────────────────────────────────────────


async def test_cleanup_removes_repo_and_calls_provider_teardown(
    bare_repo, fake_auth_provider, fake_vault
):
    config = _make_config(bare_repo)
    svc = GitService(config, fake_vault)
    with _patch_factory(fake_auth_provider):
        repo_root = await svc.clone()

    svc.cleanup(repo_root)

    assert not repo_root.exists()
    assert fake_auth_provider.teardown_called == 1


def test_cleanup_no_op_when_repo_root_already_gone(
    tmp_path, fake_auth_provider, fake_vault
):
    """cleanup() doit être idempotent / tolérant aux paths déjà supprimés."""
    config = _make_config("file:///nope")
    svc = GitService(config, fake_vault)
    # Aucun auth_provider stocké (pas de clone précédent) — teardown ne doit
    # pas lever d'exception.
    svc.cleanup(tmp_path / "ghost-dir")
