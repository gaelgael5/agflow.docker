from __future__ import annotations

from agflow.mom.adapters.generic import GenericAdapter
from agflow.mom.adapters.mistral import MistralAdapter
from agflow.services.container_runner import get_adapter


class TestAdapterRegistry:
    def test_mistral_returns_mistral_adapter(self) -> None:
        adapter = get_adapter("mistral")
        assert isinstance(adapter, MistralAdapter)

    def test_unknown_returns_generic(self) -> None:
        adapter = get_adapter("some-random-dockerfile")
        assert isinstance(adapter, GenericAdapter)
        assert not isinstance(adapter, MistralAdapter)

    def test_generic_returns_generic(self) -> None:
        adapter = get_adapter("generic")
        assert type(adapter) is GenericAdapter
