"""Actual installed Core/Foundation boundary; no provider network or model calls."""

import asyncio
import json

import pytest

from amplifier_smart_tool_stories import providers


def test_actual_public_runtime_preserves_strict_bounded_completion(tmp_path, monkeypatch):
    from amplifier_core.message_models import ChatResponse, ToolCall
    from amplifier_module_provider_openai import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-real-key")
    monkeypatch.setattr(providers, "marker", lambda config: tmp_path / "runtime.json")
    calls = []

    async def complete(self, request, **kwargs):
        calls.append(request)
        return ChatResponse(
            content=[], tool_calls=[ToolCall(id="fixture", name="submit_result", arguments={"ok": True})]
        )

    monkeypatch.setattr(OpenAIProvider, "complete", complete)
    config = providers.ProviderConfig("openai", "fixture-model", use_env=False)
    assert providers.prepare_runtime(config)["runtime"] == "amplifier-core+foundation"
    assert calls == []
    assert "fixture-not-a-real-key" not in (tmp_path / "runtime.json").read_text()

    async def run():
        bundle = await providers.prepared(config)
        assert bundle.mount_plan.get("tools", []) == []
        assert bundle.mount_plan.get("hooks", []) == []
        session = await bundle.create_session()
        async with session:
            mounted = session.coordinator.get("providers")
            assert list(mounted) == ["openai"]
            return await providers.complete(
                mounted["openai"],
                config,
                [{"role": "user", "content": "fixture"}],
                321,
                8,
                schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            )

    result, provenance = asyncio.run(run())
    assert json.loads(result) == {"ok": True}
    assert provenance["model"] == "fixture-model"
    assert len(calls) == 1
    assert calls[0].max_output_tokens == 321
    assert calls[0].timeout == 8
    assert calls[0].tool_choice == "required"
    assert calls[0].tools[0].model_dump()["strict"] is True


def test_prepare_requires_explicit_receipt_and_preserves_oauth_path(tmp_path, monkeypatch):
    monkeypatch.setenv("AMPLIFIER_AGENT_HOME", str(tmp_path / "old-agent-home"))
    assert providers.oauth_token_path() == tmp_path / "old-agent-home/state/openai-chatgpt-oauth.json"
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-real-key")
    monkeypatch.setattr(providers, "marker", lambda config: tmp_path / "absent.json")
    with pytest.raises(providers.StoriesError) as error:
        asyncio.run(providers.prepared(providers.ProviderConfig("openai")))
    assert error.value.code == "runtime_not_prepared"
