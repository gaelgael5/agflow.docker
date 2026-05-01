from __future__ import annotations

import pytest

from agflow.services.swarm_deploy_steps import (
    build_deploy_steps,
    build_rm_steps,
    slug_stack_name,
)


class TestSlugStackName:
    def test_lowercases_and_strips_uppercase(self) -> None:
        assert slug_stack_name("Foo-Bar") == "foo-bar"

    def test_replaces_invalid_chars_with_underscore(self) -> None:
        assert slug_stack_name("foo.bar/baz") == "foo_bar_baz"

    def test_keeps_alphanum_dash_underscore(self) -> None:
        assert slug_stack_name("a1_b2-c3") == "a1_b2-c3"

    def test_collapses_repeated_separators(self) -> None:
        assert slug_stack_name("foo///bar") == "foo_bar"

    def test_strips_leading_and_trailing_separators(self) -> None:
        assert slug_stack_name("---foo--") == "foo"

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(ValueError):
            slug_stack_name("")

    def test_rejects_input_that_becomes_empty_after_normalization(self) -> None:
        with pytest.raises(ValueError):
            slug_stack_name("---")

    def test_truncates_to_swarm_limit(self) -> None:
        long_name = "a" * 100
        assert len(slug_stack_name(long_name)) == 63
        assert slug_stack_name(long_name) == "a" * 63


class TestBuildDeploySteps:
    def test_returns_canonical_step_sequence(self) -> None:
        steps = build_deploy_steps(
            remote_dir="~/agflow.docker/projects/foo-1",
            compose_content="services:\n  api:\n    image: foo\n",
            env_content="API_KEY=secret\n",
            stack_name="agflow-proj-foo-1",
        )
        names = [s[0] for s in steps]
        assert names == ["mkdir", "write_stack", "write_env", "stack_deploy"]

    def test_mkdir_uses_remote_dir(self) -> None:
        steps = build_deploy_steps(
            remote_dir="~/r",
            compose_content="x",
            env_content="",
            stack_name="s",
        )
        mkdir = next(s for s in steps if s[0] == "mkdir")
        assert mkdir[1] == "mkdir -p ~/r"
        assert mkdir[2] is None

    def test_writes_compose_to_stack_yml(self) -> None:
        steps = build_deploy_steps(
            remote_dir="~/r",
            compose_content="services: {}\n",
            env_content="",
            stack_name="s",
        )
        write = next(s for s in steps if s[0] == "write_stack")
        assert write[1] == "cat > ~/r/stack.yml"
        assert write[2] == "services: {}\n"

    def test_writes_env_to_dot_env(self) -> None:
        steps = build_deploy_steps(
            remote_dir="~/r",
            compose_content="x",
            env_content="K=V\n",
            stack_name="s",
        )
        write = next(s for s in steps if s[0] == "write_env")
        assert write[1] == "cat > ~/r/.env"
        assert write[2] == "K=V\n"

    def test_deploy_command_sources_env_then_runs_stack_deploy(self) -> None:
        steps = build_deploy_steps(
            remote_dir="~/r",
            compose_content="x",
            env_content="",
            stack_name="agflow-proj-foo-1",
        )
        deploy = next(s for s in steps if s[0] == "stack_deploy")
        assert "set -a" in deploy[1]
        assert ". ~/r/.env" in deploy[1] or "source ~/r/.env" in deploy[1]
        assert "docker stack deploy" in deploy[1]
        assert "-c ~/r/stack.yml" in deploy[1]
        assert "agflow-proj-foo-1" in deploy[1]
        assert deploy[2] is None

    def test_deploy_command_uses_resolve_image_digests_flag(self) -> None:
        steps = build_deploy_steps(
            remote_dir="~/r",
            compose_content="x",
            env_content="",
            stack_name="s",
        )
        deploy = next(s for s in steps if s[0] == "stack_deploy")
        # Pin to image tags as written; rejecting digest resolution avoids
        # an extra registry round-trip and silent retags.
        assert "--resolve-image=never" in deploy[1]

    def test_extra_steps_are_inserted_before_deploy(self) -> None:
        login_step = ("registry_login", "docker login -u u -p p reg", None)
        steps = build_deploy_steps(
            remote_dir="~/r",
            compose_content="x",
            env_content="",
            stack_name="s",
            extra_steps_before_deploy=[login_step],
        )
        names = [s[0] for s in steps]
        assert names == [
            "mkdir",
            "write_stack",
            "write_env",
            "registry_login",
            "stack_deploy",
        ]


class TestBuildRmSteps:
    def test_returns_single_stack_rm_step(self) -> None:
        steps = build_rm_steps("agflow-proj-foo-1")
        assert len(steps) == 1
        name, cmd, stdin = steps[0]
        assert name == "stack_rm"
        assert cmd == "docker stack rm agflow-proj-foo-1"
        assert stdin is None

    def test_normalizes_stack_name(self) -> None:
        steps = build_rm_steps("Foo.Bar")
        assert steps[0][1] == "docker stack rm foo_bar"
