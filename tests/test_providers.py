import json

import pytest

from amplifier_smart_tool_stories import Stories, StoriesError
from amplifier_smart_tool_stories.providers import ENV, ProviderConfig


@pytest.mark.parametrize("name", ["openai", "anthropic", "gemini", "copilot"])
def test_missing_native_credentials_do_not_boot_runtime(monkeypatch, name):
    for keys in ENV.values():
        for key in keys:
            monkeypatch.delenv(key, raising=False)
    with pytest.raises(StoriesError) as exc:
        ProviderConfig(name).entry()
    assert exc.value.code == "provider_unavailable"


@pytest.mark.parametrize("alias,canonical", [("openai-chatgpt", "chatgpt"), ("github-copilot", "copilot")])
def test_subscription_provider_aliases(alias, canonical):
    assert ProviderConfig(alias).provider == canonical


def test_snapshot_does_not_resolve_new_ambient_defaults(monkeypatch):
    monkeypatch.setenv("STORIES_MODEL", "later-model")
    assert ProviderConfig("openai", None, use_env=False).model is None
    assert ProviderConfig("openai").model == "later-model"


def test_redaction_and_configuration_do_not_spend(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-value")
    api = Stories(tmp_path)
    assert "secret-test-value" not in json.dumps(api.provider_settings())
    for provider in ["openai", "chatgpt", "copilot", "anthropic", "gemini"]:
        assert api.configure_provider(provider)["provider"] == provider
    with pytest.raises(StoriesError) as exc:
        api.test_provider()
    assert exc.value.code == "model_access_required"


def test_all_capabilities_have_cli_help(tmp_path):
    import subprocess
    import sys

    from amplifier_smart_tool_stories.lib import CAPABILITIES

    for name in CAPABILITIES:
        p = subprocess.run(
            [sys.executable, "-m", "amplifier_smart_tool_stories", name.replace("_", "-"), "--help"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert p.returncode == 0 and "--input" in p.stdout


def test_runtime_receipt_never_cold_prepares_or_accepts_changed_code(tmp_path, monkeypatch):
    from amplifier_smart_tool_stories import providers

    mark = tmp_path / "runtime.json"
    monkeypatch.setattr(providers, "marker", lambda config: mark)
    identity = {"version": 2, "packages": {"provider-openai": {"code_sha256": "first"}}}
    monkeypatch.setattr(providers, "_runtime_identity", lambda config: identity)
    config = ProviderConfig("openai")
    with pytest.raises(StoriesError, match="missing or changed"):
        providers._load_local_runtime(config)
    mark.write_text(json.dumps(identity))
    assert providers._load_local_runtime(config) == identity
    identity["packages"]["provider-openai"]["code_sha256"] = "changed"
    with pytest.raises(StoriesError, match="missing or changed"):
        providers._load_local_runtime(config)
    mark.write_text("invalid")
    with pytest.raises(StoriesError, match="missing or changed"):
        providers._load_local_runtime(config)


def test_in_process_cli_reports_model_failure_nonzero(tmp_path):
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in ENV["openai"]}
    payload = {
        "title": "Test",
        "purpose": "Explain",
        "audience": "Reader",
        "sources": [{"id": "s", "content": "A supplied fact."}],
        "grant": {"timeout_seconds": 10},
        "request_id": "missing-key",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "amplifier_smart_tool_stories",
            "--store",
            str(tmp_path),
            "--provider",
            "openai",
            "--model-env",
            "--execution",
            "in_process",
            "generate",
            "--input",
            json.dumps(payload),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["operation"]["state"] == "failed"


def test_native_submission_uses_schema_and_rejects_missing_submission():
    import asyncio
    from types import SimpleNamespace

    from amplifier_smart_tool_stories.providers import complete
    from amplifier_smart_tool_stories.submissions import REVIEW

    class Provider:
        default_model = "test"
        calls = []

        async def complete(self, request):
            self.calls.append(request)
            return SimpleNamespace(
                content=[],
                usage=None,
                tool_calls=[SimpleNamespace(name="submit_result", arguments={"submitted": True})],
            )

    p = Provider()
    text, _ = asyncio.run(
        complete(p, ProviderConfig("openai"), [{"role": "user", "content": "Review"}], 100, 10, schema=REVIEW)
    )
    assert json.loads(text) == {"submitted": True}
    assert p.calls[0].tools[0].parameters == REVIEW
    assert p.calls[0].tool_choice == "required"
    assert p.calls[0].tools[0].strict is True

    async def missing(request):
        return SimpleNamespace(content=[], usage=None, tool_calls=[])

    p.complete = missing
    with pytest.raises(StoriesError) as exc:
        asyncio.run(complete(p, ProviderConfig("openai"), [], 100, 10, schema=REVIEW))
    assert exc.value.code == "invalid_model_result"


def test_apply_changes_future_feedback_only_and_keeps_authority(tmp_path, monkeypatch):
    monkeypatch.setenv("STORIES_MODEL", "ambient-model")
    api = Stories(tmp_path, provider="openai", model="original")
    r = api.create_story("Test", "<html><body><p>Text</p></body></html>", "s")
    api.grant_feedback(r["story_id"], {"max_operations": 3}, "grant")
    old = api.add_comment(r["story_id"], r["revision_id"], "Old", "old")
    grant = api.get_story(r["story_id"])["feedback_grant"].copy()
    api.configure_provider("anthropic")
    assert api.config.model is None  # Clearing model must not restore another provider's env model.
    new = api.add_comment(r["story_id"], r["revision_id"], "New", "new")
    assert api.get_operation(old["operation_id"])["provider"] == {"provider": "openai", "model": "original"}
    assert api.get_operation(new["operation_id"])["provider"] == {"provider": "anthropic", "model": None}
    after = api.get_story(r["story_id"])["feedback_grant"]
    assert after == {**grant, "used": grant["used"] + 1}
    fresh = Stories(tmp_path, provider="gemini")
    assert not fresh._feedback_provider_override


def test_login_and_discovery_require_access_without_starting(tmp_path, monkeypatch):
    api = Stories(tmp_path)
    for method in (api.provider_login, api.provider_models):
        with pytest.raises(StoriesError) as exc:
            method(provider="chatgpt")
        assert exc.value.code == "model_access_required"


def test_discovery_uses_selected_prepared_provider(monkeypatch):
    from amplifier_smart_tool_stories import providers

    class Provider:
        default_model = "chosen"

        async def list_models(self):
            return [{"id": "chosen", "display_name": "Chosen", "secret": "omit"}]

    class Session:
        coordinator = {"providers": {"p": Provider()}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Bundle:
        async def create_session(self):
            return Session()

    async def prepared(config):
        assert config.provider == "gemini"
        return Bundle()

    monkeypatch.setattr(providers, "prepared", prepared)
    result = providers.provider_models(ProviderConfig("gemini"))
    assert result["models"] == [{"id": "chosen", "name": "Chosen"}]
    assert result["default_model"] == "chosen"


def test_owned_provider_job_cancellation_cleans_up(monkeypatch):
    import asyncio
    import threading

    from amplifier_smart_tool_stories import providers

    cancelled = threading.Event()
    finished = []

    async def work():
        try:
            cancelled.set()
            await asyncio.sleep(10)
        finally:
            finished.append(True)

    monkeypatch.setattr(providers._job_context, "cancel", cancelled, raising=False)
    with pytest.raises(StoriesError) as exc:
        providers._run_provider(work(), 20)
    assert exc.value.code == "provider_cancelled"
    assert finished == [True]


def test_chatgpt_login_relays_device_instructions_without_mount(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from amplifier_smart_tool_stories import providers

    instructions = []

    async def login(*, token_file_path, print_fn):
        assert token_file_path == str(tmp_path / "tokens.json")
        print_fn("Open https://example.test/device and enter TEST-CODE")

    monkeypatch.setattr(providers, "oauth_token_path", lambda: tmp_path / "tokens.json")
    original = providers.importlib.import_module
    monkeypatch.setattr(
        providers.importlib,
        "import_module",
        lambda name: SimpleNamespace(login=login) if name.endswith(".oauth") else original(name),
    )
    result = providers.provider_login(ProviderConfig("chatgpt"), on_progress=instructions.append)
    assert result["status"] == "succeeded"
    assert instructions == ["Open https://example.test/device and enter TEST-CODE"]


def test_copilot_login_uses_native_cache_and_never_reports_token(monkeypatch):
    import asyncio

    from amplifier_smart_tool_stories import providers

    calls = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"private-github-token", b""

    async def command(*args, **kwargs):
        calls.append(args)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", command)
    monkeypatch.setenv("GH_TOKEN", "before")
    result = providers.provider_login(ProviderConfig("copilot"))
    assert calls == [("gh", "auth", "token", "--hostname", "github.com")]
    assert providers.os.environ["GH_TOKEN"] == "private-github-token"
    assert "private-github-token" not in json.dumps(result)


def test_login_timeout_is_actionable(monkeypatch):
    import asyncio

    from amplifier_smart_tool_stories import providers

    async def timeout(*args):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(providers, "_login", timeout)
    with pytest.raises(StoriesError) as exc:
        providers.provider_login(ProviderConfig("chatgpt"), 1)
    assert exc.value.code == "provider_login_failed"
    assert "Sign in" in exc.value.public()["error"]["remedy"]


def test_anthropic_submission_uses_native_strict_custom_tool():
    from amplifier_smart_tool_stories.providers import submission_tool
    from amplifier_smart_tool_stories.submissions import REVIEW

    tool = submission_tool(ProviderConfig("anthropic"), REVIEW)
    assert tool.type == "custom"
    assert tool.strict is True
    assert tool.input_schema["properties"]["semantic"]["type"] == "object"
    assert tool.input_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "name,env_name,field,module",
    [
        ("openai", "OPENAI_API_KEY", "api_key", "provider-openai"),
        ("anthropic", "ANTHROPIC_API_KEY", "api_key", "provider-anthropic"),
        ("gemini", "GEMINI_API_KEY", "api_key", "provider-gemini"),
        ("copilot", "GH_TOKEN", "github_token", "provider-github-copilot"),
    ],
)
def test_public_provider_entries_preserve_credentials_and_explicit_model(
    monkeypatch, name, env_name, field, module
):
    for names in ENV.values():
        for key in names:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(env_name, "fixture-value")
    assert ProviderConfig(name, "chosen-model", use_env=False).entry() == {
        "module": module,
        "config": {"default_model": "chosen-model", field: "fixture-value"},
    }


def test_prepare_rejects_installed_code_change_before_writing_receipt(tmp_path, monkeypatch):
    from amplifier_smart_tool_stories import providers

    identities = iter([{"version": 1}, {"version": 1}, {"version": 2}])
    monkeypatch.setattr(providers, "_runtime_identity", lambda _: next(identities))
    monkeypatch.setattr(providers, "marker", lambda _: tmp_path / "receipt.json")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-real-key")
    with pytest.raises(StoriesError) as error:
        providers.prepare_runtime(ProviderConfig("openai"))
    assert error.value.code == "runtime_not_prepared"
    assert not (tmp_path / "receipt.json").exists()
