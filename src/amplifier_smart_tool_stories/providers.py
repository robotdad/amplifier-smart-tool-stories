"""Amplifier provider adapter. Credentials stay in env/provider-owned caches, never story state."""

import asyncio
import copy
import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from .errors import StoriesError, require

# Dashboard workers may cancel owned setup when their service stops.
_job_context = threading.local()


def _run_provider(coroutine, timeout):
    async def supervise():
        event = getattr(_job_context, "cancel", None)
        if event is not None and event.is_set():
            coroutine.close()
            raise StoriesError("provider_cancelled", "Provider setup stopped with the viewer.")
        task = asyncio.create_task(asyncio.wait_for(coroutine, timeout))
        try:
            while not task.done():
                event = getattr(_job_context, "cancel", None)
                if event is not None and event.is_set():
                    raise StoriesError("provider_cancelled", "Provider setup stopped with the viewer.")
                await asyncio.wait({task}, timeout=0.1)
            return await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return asyncio.run(supervise())


PROVIDERS = {
    "openai": "openai",
    "chatgpt": "openai-chatgpt",
    "copilot": "github-copilot",
    "anthropic": "anthropic",
    "gemini": "gemini",
}
ENV = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "copilot": ("COPILOT_AGENT_TOKEN", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
}
SETUP = {
    "openai": "Set OPENAI_API_KEY.",
    "anthropic": "Set ANTHROPIC_API_KEY.",
    "gemini": "Set GOOGLE_API_KEY or GEMINI_API_KEY; GOOGLE_API_KEY takes precedence.",
    "copilot": "Choose Sign in to use GitHub CLI authentication. An account with Copilot access and installed gh are required. Native Copilot/GitHub environment tokens are also supported.",
    "chatgpt": "Choose Sign in to complete ChatGPT device authorization. Tokens stay in the provider OAuth cache.",
}


class ProviderConfig:
    def __init__(self, provider=None, model=None, *, use_env=True):
        name = provider or (os.environ.get("STORIES_PROVIDER", "openai") if use_env else "openai")
        aliases = {v: k for k, v in PROVIDERS.items()}
        self.provider = aliases.get(name, name)
        require(self.provider in PROVIDERS, "Choose openai, chatgpt, copilot, anthropic, or gemini.")
        self.model = model or (os.environ.get("STORIES_MODEL") if use_env else None) or None
        require(
            self.model is None or isinstance(self.model, str) and len(self.model) < 200,
            "Model must be a short string.",
        )

    def public(self):
        return {"provider": self.provider, "model": self.model}

    def entry(self):
        name = PROVIDERS[self.provider]
        if self.provider != "chatgpt":
            key = next((key for key in ENV[self.provider] if os.environ.get(key)), None)
            if not key:
                raise StoriesError(
                    "provider_unavailable", f"{self.provider} credentials are missing.", SETUP[self.provider]
                )
        else:
            if not _oauth().load_tokens(str(oauth_token_path())):
                raise StoriesError(
                    "provider_unavailable", "ChatGPT OAuth is not configured.", SETUP[self.provider]
                )
        entry = {"module": "provider-" + name, "config": {}}
        if self.model:
            entry["config"]["default_model"] = self.model
        if self.provider != "chatgpt":
            entry["config"]["github_token" if self.provider == "copilot" else "api_key"] = os.environ[key]
        else:
            entry["config"].update(login_on_mount=False, token_file_path=str(oauth_token_path()))
        return entry


def settings(config):
    rows = []
    for name in PROVIDERS:
        keys = ENV.get(name, ())
        key = next((key for key in keys if os.environ.get(key)), None)
        row = {"name": name, "configured": bool(key), "source": key or "none", "setup": SETUP[name]}
        if name == "chatgpt":
            row.update(
                configured=bool(_oauth().load_tokens(str(oauth_token_path()))),
                source="provider OAuth cache",
            )
        try:
            _load_local_runtime(ProviderConfig(name, use_env=False))
            row["runtime_ready"] = True
        except StoriesError:
            row["runtime_ready"] = False
        rows.append(row)
    return {
        "effective": config.public(),
        "scope": "This running session only. Applies to future operations and feedback; queued work keeps its provider.",
        "providers": rows,
    }


def _oauth():
    # Provider-owned, public OAuth helpers; no agent CLI/cache implementation.
    return importlib.import_module("amplifier_module_provider_openai_chatgpt.oauth")


def oauth_token_path():
    # Preserve the cache used by earlier Stories installations; never migrate or
    # delete credentials as part of this adapter update. The provider owns I/O.
    root = Path(os.environ.get("AMPLIFIER_AGENT_HOME", Path.home() / ".amplifier-agent")).expanduser()
    return root / "state" / "openai-chatgpt-oauth.json"


def marker(config):
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    environment = hashlib.sha256(sys.prefix.encode()).hexdigest()[:20]
    return cache / "amplifier-stories" / "runtime-v2" / environment / f"{config.provider}.json"


def _runtime_identity(config):
    """Seal the selected installed runtime; never resolve or download source."""
    names = [
        "amplifier-core",
        "amplifier-foundation",
        "amplifier-module-loop-streaming",
        "amplifier-module-context-simple",
        "amplifier-module-provider-" + PROVIDERS[config.provider],
    ]
    packages = {}
    for name in names:
        dist = importlib.metadata.distribution(name)
        files = []
        for item in dist.files or []:
            if str(item).endswith((".py", ".so", ".pyd")) and ".dist-info/" not in str(item):
                path = Path(dist.locate_file(item))
                files.append((str(item), hashlib.sha256(path.read_bytes()).hexdigest()))
        require(bool(files), "Runtime package has no verifiable installed code.", "runtime_not_prepared")
        packages[name] = {
            "version": dist.version,
            "code_sha256": hashlib.sha256(
                json.dumps(sorted(files), separators=(",", ":")).encode()
            ).hexdigest(),
        }
    return {"version": 2, "python_prefix": sys.prefix, "packages": packages}


def _load_local_runtime(config):
    try:
        identity = _runtime_identity(config)
        if json.loads(marker(config).read_text()) != identity:
            raise ValueError("Installed runtime changed")
        return identity
    except Exception:
        raise StoriesError(
            "runtime_not_prepared",
            "This provider's runtime is missing or changed since preparation.",
            "Run stories --provider NAME prepare-runtime explicitly, then retry with a new request_id.",
        ) from None


async def prepared(config, allow_prepare=False):
    from amplifier_foundation import Bundle

    entry = config.entry()  # Fail before runtime work when credentials are missing.
    _runtime_identity(config) if allow_prepare else _load_local_runtime(config)
    if config.provider == "chatgpt":
        oauth = _oauth()
        token_path = entry["config"]["token_file_path"]
        tokens = oauth.load_tokens(token_path)
        if not oauth.is_token_valid(tokens) and tokens and tokens.get("refresh_token"):
            tokens = await oauth.refresh_tokens(tokens["refresh_token"], path=token_path)
        if not oauth.is_token_valid(tokens):
            raise StoriesError("provider_unavailable", "ChatGPT login is expired.", SETUP["chatgpt"])
    # All modules are declared installation dependencies. Source-less entries use
    # Core's installed entry points; no bundle source, resolver install or tool
    # authority is inherited from the invoking host.
    bundle = Bundle(
        name="stories-provider",
        providers=[entry],
        tools=[],
        hooks=[],
        agents={},
        session={"orchestrator": {"module": "loop-streaming"}, "context": {"module": "context-simple"}},
    )
    return await bundle.prepare(install_deps=False)


def prepare_runtime(config):
    async def run():
        identity = _runtime_identity(config)
        bundle = await prepared(config, allow_prepare=True)
        session = await bundle.create_session()
        async with session:
            require(
                bool(session.coordinator.get("providers")),
                "Provider failed to mount.",
                "provider_unavailable",
            )
        require(
            _runtime_identity(config) == identity,
            "Installed runtime changed during preparation.",
            "runtime_not_prepared",
        )
        mark = marker(config)
        mark.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=mark.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(identity, handle)
        try:
            temporary.replace(mark)
        finally:
            temporary.unlink(missing_ok=True)
        return {"status": "succeeded", "provider": config.provider, "runtime": "amplifier-core+foundation"}

    try:
        return _run_provider(run(), 300)
    except StoriesError:
        raise
    except Exception as exc:
        raise StoriesError(
            "runtime_prepare_failed",
            f"Runtime preparation failed ({type(exc).__name__}).",
            "Check provider credentials and reinstall Stories with its declared Amplifier dependencies.",
        ) from None


def submission_tool(config, schema):
    """Use the provider's native strict submission format where supported.

    Anthropic custom-tool passthrough preserves strict/input_schema; the generic
    function conversion in the installed adapter drops strict. No cache patches.
    """
    from amplifier_core.message_models import ToolSpec

    fields = {
        "name": "submit_result",
        "description": "Submit the requested structured result. No external action.",
        "parameters": schema,
    }
    if config.provider == "anthropic":
        from anthropic import transform_schema

        fields.update(type="custom", input_schema=transform_schema(copy.deepcopy(schema)), strict=True)
    elif config.provider == "openai":
        fields["strict"] = True
    return ToolSpec(**fields)


async def complete(provider, config, messages, max_tokens, timeout, schema=None):
    from amplifier_core.message_models import ChatRequest, Message

    response = await provider.complete(
        ChatRequest(
            messages=[Message(**m) for m in messages],
            model=config.model,
            max_output_tokens=max_tokens,
            timeout=timeout,
            tools=[submission_tool(config, schema)] if schema else None,
            tool_choice="required" if schema else None,
        )
    )
    content = response.content
    if isinstance(content, str):
        text = content
    else:
        text = "".join(getattr(part, "text", "") or "" for part in content)
    if schema:
        submissions = [call for call in response.tool_calls or [] if call.name == "submit_result"]
        require(
            len(submissions) == 1 and len(response.tool_calls or []) == 1,
            "Expected one structured submission.",
            "invalid_model_result",
        )
        text = json.dumps(submissions[0].arguments)
    usage = getattr(response, "usage", None)
    usage = usage.model_dump() if hasattr(usage, "model_dump") else {}
    return text, {
        "provider": config.provider,
        "model": config.model or getattr(provider, "default_model", None),
        "usage": {k: v for k, v in usage.items() if isinstance(v, (float, int))},
    }


def test_provider(config, timeout_seconds):
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 300, "Timeout must be 1–300 seconds.")

    async def run():
        bundle = await prepared(config)
        session = await bundle.create_session()
        async with session:
            mounted = session.coordinator.get("providers")
            require(bool(mounted), "Provider failed to mount.", "provider_unavailable")
            text, provenance = await complete(
                next(iter(mounted.values())),
                config,
                [{"role": "user", "content": "Reply with OK only."}],
                128,
                timeout_seconds,
            )
            require(bool(text.strip()), "Provider returned no text.", "invalid_model_result")
            return {"status": "succeeded", **provenance}

    try:
        return _run_provider(run(), timeout_seconds)
    except StoriesError:
        raise
    except Exception as exc:
        raise StoriesError(
            "provider_test_failed",
            f"Connection test failed ({type(exc).__name__}).",
            "Check credentials, model access and provider availability. No fallback was used.",
        ) from None


def provider_models(config, timeout_seconds=60):
    """Discover native model IDs without generating content or starting login."""
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 300, "Timeout must be 1–300 seconds.")

    async def run():
        bundle = await prepared(config)
        session = await bundle.create_session()
        async with session:
            mounted = session.coordinator.get("providers")
            require(bool(mounted), "Provider failed to mount.", "provider_unavailable")
            provider = next(iter(mounted.values()))
            models = await provider.list_models()
            rows = []
            for model in models:
                data = model.model_dump() if hasattr(model, "model_dump") else model
                if isinstance(data, dict) and isinstance(data.get("id"), str):
                    rows.append({"id": data["id"], "name": data.get("display_name") or data["id"]})
                elif isinstance(data, str):
                    rows.append({"id": data, "name": data})
            return {
                "provider": config.provider,
                "models": rows,
                "default_model": getattr(provider, "default_model", None),
                "notice": "Model listing does not guarantee account access or image/tool compatibility.",
            }

    try:
        return _run_provider(run(), timeout_seconds)
    except StoriesError:
        raise
    except Exception as exc:
        raise StoriesError(
            "provider_models_failed",
            f"Model discovery failed ({type(exc).__name__}).",
            "Check runtime preparation, credentials and provider availability.",
        ) from None


async def _login(config, timeout_seconds, progress):
    if config.provider == "copilot":

        async def gh(*args, stream=False):
            proc = await asyncio.create_subprocess_exec(
                "gh",
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT if stream else asyncio.subprocess.DEVNULL,
                env={**os.environ, "GH_BROWSER": "echo"},
            )
            try:
                if stream:
                    async for line in proc.stdout:
                        progress(line.decode(errors="replace").rstrip())
                    return await proc.wait(), b""
                output, _ = await proc.communicate()
                return proc.returncode, output
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

        code, token = await gh("auth", "token", "--hostname", "github.com")
        if code:
            progress("Complete GitHub device authorization using the URL and code below.")
            code, _ = await gh("auth", "login", "--hostname", "github.com", "--web", stream=True)
            require(code == 0, "GitHub sign-in did not complete.", "provider_login_failed")
            code, token = await gh("auth", "token", "--hostname", "github.com")
        require(
            code == 0 and bool(token.strip()), "GitHub CLI has no token available.", "provider_login_failed"
        )
        os.environ["GH_TOKEN"] = token.decode().strip()
        return {
            "status": "succeeded",
            "provider": "copilot",
            "notice": "GitHub CLI owns the login. This session can use it; Copilot subscription access still needs a connection test.",
        }
    if config.provider != "chatgpt":
        return {"status": "action_required", "provider": config.provider, "notice": SETUP[config.provider]}
    oauth = _oauth()
    await oauth.login(token_file_path=str(oauth_token_path()), print_fn=progress)
    return {
        "status": "succeeded",
        "provider": "chatgpt",
        "notice": "Login saved in the provider OAuth cache.",
    }


def provider_login(config, timeout_seconds=300, on_progress=None):
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 600, "Timeout must be 1–600 seconds.")
    try:
        return _run_provider(
            _login(config, timeout_seconds, on_progress or (lambda _: None)), timeout_seconds
        )
    except StoriesError:
        raise
    except Exception as exc:
        raise StoriesError(
            "provider_login_failed",
            f"Sign-in did not complete ({type(exc).__name__}).",
            SETUP[config.provider],
        ) from None
