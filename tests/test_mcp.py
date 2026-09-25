"""Portable MCP discovery, resource isolation and shared library semantics."""

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
import anyio
from mcp import Client, StdioServerParameters
from mcp.client import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from test_stories import SOURCE

from amplifier_smart_tool_stories import Stories
from amplifier_smart_tool_stories.errors import StoriesError
from amplifier_smart_tool_stories.mcp import CHUNK_BYTES, UI_URI, create_server

APPS = advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})
SEED_PATH = Path(__file__).parent / "fixtures" / "mcp_seed.py"
spec = importlib.util.spec_from_file_location("mcp_seed", SEED_PATH)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def value(result):
    assert not result.is_error, result.content
    return result.structured_content["result"]


def test_typed_grants_resources_and_provider_free_status(tmp_path):
    async def run():
        api = Stories(tmp_path)
        async with Client(create_server(api), extensions=[APPS]) as client:
            tools = (await client.list_tools()).tools
            assert {
                "stories_generate",
                "stories_get_story",
                "stories_get_preview",
                "stories_save_draft",
                "stories_status",
            } <= {tool.name for tool in tools}
            generate = next(t for t in tools if t.name == "stories_generate")
            assert generate.meta["ui"]["visibility"] == ["model", "app"]
            assert generate.input_schema["$defs"]["Grant"]["properties"]["timeout_seconds"]["maximum"] == 900
            assert generate.input_schema["$defs"]["Grant"]["additionalProperties"] is False
            assert {"stories_accept_revision", "stories_start_provider_job", "stories_get_video_export"} <= {
                t.name for t in tools
            }
            status = (await client.call_tool("stories_status", {})).structured_content
            assert status["model_access"] is False
            rejected = await client.call_tool(
                "stories_generate",
                {
                    "title": "Draft",
                    "purpose": "Explain",
                    "audience": "Team",
                    "sources": [SOURCE],
                    "grant": {"max_operations": 0},
                    "request_id": "invalid",
                },
            )
            assert rejected.is_error and api.list_stories() == []
            rejected = await client.call_tool(
                "stories_generate",
                {
                    "title": "Draft",
                    "purpose": "Explain",
                    "audience": "Team",
                    "sources": [SOURCE],
                    "grant": {},
                    "request_id": "no-model",
                },
            )
            assert (
                rejected.is_error and rejected.structured_content["error"]["code"] == "model_access_required"
            )
            resource = (await client.read_resource(UI_URI)).contents[0]
            assert resource.mime_type == APP_MIME_TYPE and "<script src=" not in resource.text
            assert resource.meta["ui"]["csp"]["connectDomains"] == []
            assert 'sandbox="allow-scripts"' in resource.text
            assert len((await client.list_resource_templates()).resource_templates) == 4

    anyio.run(run)


def test_shared_drafts_comments_direction_choices_and_retry(tmp_path):
    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path)
        sid, rid = ids["story_id"], ids["revision_id"]
        async with Client(create_server(api), extensions=[APPS]) as client:
            draft = {
                "story_id": sid,
                "revision_id": rid,
                "draft_id": "shared-review",
                "sequence": 2,
                "text": "Keep the handoff clear",
            }
            assert value(await client.call_tool("stories_save_draft", draft))["status"] == "saved"
            assert (
                value(await client.call_tool("stories_save_draft", {**draft, "sequence": 1, "text": "old"}))[
                    "status"
                ]
                == "stale"
            )
            assert api.get_story(sid)["drafts"]["shared-review"]["text"] == draft["text"]
            assert not api.get_story(sid)["annotations"]
            args = {
                "story_id": sid,
                "revision_id": rid,
                "text": "Review the first panel",
                "request_id": "note",
            }
            first = value(await client.call_tool("stories_add_comment", args))
            assert value(await client.call_tool("stories_add_comment", args)) == first
            assert api.get_story(sid)["annotations"][0]["author"] == "agent"
            assert first["operation_id"] is None
            api.grant_feedback(sid, {"max_operations": 1}, "test-feedback")
            followup = value(
                await client.call_tool(
                    "stories_respond",
                    {
                        "story_id": sid,
                        "annotation_id": first["annotation_id"],
                        "text": "Agent follow-up",
                        "request_id": "agent-response",
                    },
                )
            )
            assert followup["operation_id"] is None
            assert api.get_story(sid)["annotations"][-1]["author"] == "agent"
            assert api.get_story(sid)["feedback_grant"]["used"] == 0
            user = value(
                await client.call_tool(
                    "stories_add_comment", {**args, "request_id": "user", "author": "user"}
                )
            )
            assert user["status"] == "queued"
            receipt = value(
                await client.call_tool(
                    "stories_select_direction", {"story_id": sid, "revision_id": rid, "request_id": "select"}
                )
            )
            state = value(await client.call_tool("stories_get_story", {"story_id": sid}))
            assert state["selected_direction"] == receipt["direction_id"] and not state.get("acceptances")
            assert api.get_story(sid)["drafts"]["shared-review"]["text"] == draft["text"]

    anyio.run(run)


def test_retained_media_and_exports_use_scoped_chunk_resources(tmp_path):
    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path)
        sid, rid, asset = ids["story_id"], ids["revision_id"], ids["asset_id"]
        async with Client(create_server(api)) as client:
            media = value(
                await client.call_tool(
                    "stories_get_media", {"story_id": sid, "revision_id": rid, "asset_id": asset}
                )
            )
            assert "data_base64" not in media and media["chunk_bytes"] == CHUNK_BYTES
            blob = (await client.read_resource(media["resource_uri"])).contents[0]
            assert base64.b64decode(blob.blob) == base64.b64decode(
                api.get_media(sid, rid, asset)["data_base64"]
            )
            with pytest.raises(Exception):
                await client.read_resource(media["resource_uri"].replace(asset, "missing-asset"))
            with pytest.raises(Exception):
                await client.read_resource(media["resource_uri"].removesuffix("/0") + "/1")
            exported = value(
                await client.call_tool(
                    "stories_get_export", {"story_id": sid, "revision_id": rid, "format": "zip"}
                )
            )
            raw = (await client.read_resource(exported["resource_uri"])).contents[0]
            assert base64.b64decode(raw.blob).startswith(b"PK")
            with pytest.raises(Exception):
                await client.read_resource("file:///etc/passwd")

    anyio.run(run)


def test_stdio_reconnect_keeps_retained_work_without_starting_models(tmp_path):
    ids = fixture.seed(tmp_path)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "amplifier_smart_tool_stories.mcp", "--storage", str(tmp_path)],
        env={"PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )

    async def run():
        for _ in range(2):
            async with Client(params) as client:
                state = value(await client.call_tool("stories_get_story", {"story_id": ids["story_id"]}))
                assert len(state["revisions"]) == 2 and not state["annotations"]

    anyio.run(run)


def test_help_is_provider_free_and_does_not_create_a_store(tmp_path):
    env = {
        key: val
        for key, val in os.environ.items()
        if not any(word in key for word in ("API_KEY", "TOKEN", "SECRET"))
    }
    result = subprocess.run(
        [sys.executable, "-m", "amplifier_smart_tool_stories.mcp", "--help"],
        env=env,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0 and "--storage" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_shared_review_view_is_versioned_persistent_and_not_direction_choice(tmp_path):
    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path)
        sid = ids["story_id"]
        originally_selected = api.get_story(sid)["selected_revision"]
        async with Client(create_server(api)) as client:
            initial = value(await client.call_tool("stories_get_review_view", {"story_id": sid}))
            args = {
                "story_id": sid,
                "expected_version": initial["version"],
                "request_id": "view-position",
                "revision_id": ids["revision_id"],
                "slide": 1,
                "comparison_revision": ids["comparison_revision"],
                "panel_open": True,
                "sections": ["sources"],
                "export_format": "zip",
            }
            changed = value(await client.call_tool("stories_update_review_view", args))
            assert changed["version"] == 1 and changed["slide"] == 1
            assert value(await client.call_tool("stories_update_review_view", args)) == changed
            conflict = await client.call_tool(
                "stories_update_review_view", {**args, "request_id": "stale", "slide": 1}
            )
            assert conflict.is_error and conflict.structured_content["error"]["code"] == "view_conflict"
            bad = await client.call_tool(
                "stories_update_review_view", {**args, "expected_version": 1, "request_id": "bad", "slide": 3}
            )
            assert bad.is_error
            assert Stories(tmp_path).get_review_view(sid) == changed
            assert api.get_story(sid)["selected_direction"] is None
            assert api.get_story(sid)["selected_revision"] == originally_selected
            assert not api.get_story(sid).get("acceptances")
            assert len(api.get_story(sid)["revisions"]) == 2 and not api.get_story(sid)["annotations"]

    anyio.run(run)


def test_export_resources_reuse_one_immutable_preparation(tmp_path, monkeypatch):
    import hashlib

    async def run():
        api = Stories(tmp_path)
        preparations = []

        def export(story_id, revision_id, format="html"):
            data = bytes([len(preparations) + 1]) * (CHUNK_BYTES + 100)
            preparations.append(data)
            return {"data_base64": base64.b64encode(data).decode(), "mime_type": "application/zip"}

        monkeypatch.setattr(api, "get_export", export)
        async with Client(create_server(api)) as client:
            args = {"story_id": "story", "revision_id": "revision", "format": "zip"}
            one = value(await client.call_tool("stories_get_export", args))
            two = value(await client.call_tool("stories_get_export", args))
            assert one["resource_uri"] != two["resource_uri"]
            output = b""
            for offset in (0, CHUNK_BYTES):
                resource = await client.read_resource(
                    one["resource_uri"].removesuffix("/0") + "/" + str(offset)
                )
                output += base64.b64decode(resource.contents[0].blob)
            assert len(preparations) == 2 and output == preparations[0]
            assert hashlib.sha256(output).hexdigest() == one["transfer_sha256"]

    anyio.run(run)


def test_user_comments_preserve_grants_when_mcp_cannot_execute_them(tmp_path):
    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path, execution="in_process")
        api.grant_feedback(ids["story_id"], {"max_operations": 2}, "feedback-permission")
        async with Client(create_server(api)) as client:
            comment = {
                "story_id": ids["story_id"],
                "revision_id": ids["revision_id"],
                "text": "Clarify the handoff",
                "request_id": "feedback",
                "author": "user",
            }
            receipt = value(await client.call_tool("stories_add_comment", comment))
            assert receipt["status"] == "awaiting_model_access" and receipt["operation_id"] is None
            assert value(await client.call_tool("stories_add_comment", comment)) == receipt
            parent = value(
                await client.call_tool(
                    "stories_add_comment",
                    {
                        "story_id": ids["story_id"],
                        "revision_id": ids["revision_id"],
                        "text": "Agent clarification",
                        "request_id": "agent-note",
                    },
                )
            )
            response = {
                "story_id": ids["story_id"],
                "annotation_id": parent["annotation_id"],
                "text": "User response",
                "request_id": "response",
                "author": "user",
            }
            reply = value(await client.call_tool("stories_respond", response))
            assert reply["status"] == "awaiting_model_access" and reply["operation_id"] is None
            assert value(await client.call_tool("stories_respond", response)) == reply
            assert api.get_story(ids["story_id"])["feedback_grant"]["used"] == 0

    anyio.run(run)


def test_mcp_user_comments_consume_grants_only_with_injected_execution(tmp_path):
    async def run():
        ids = fixture.seed(tmp_path)
        calls = []

        def intelligence(story, operation):
            calls.append(operation["id"])
            return {
                "action": "answer",
                "message": "Retained fixture response",
                "changes": {"summary": "", "material_changes": [], "omissions": [], "assumptions": []},
                "calculations": [],
            }

        api = Stories(tmp_path, execution="in_process", intelligence=intelligence)
        api.grant_feedback(ids["story_id"], {"max_operations": 2}, "feedback-permission")
        async with Client(create_server(api)) as client:
            comment = {
                "story_id": ids["story_id"],
                "revision_id": ids["revision_id"],
                "text": "Clarify the handoff",
                "request_id": "feedback",
                "author": "user",
            }
            receipt = value(await client.call_tool("stories_add_comment", comment))
            assert receipt["status"] == "queued"
            assert api.get_operation(receipt["operation_id"])["state"] == "succeeded"
            assert value(await client.call_tool("stories_add_comment", comment)) == receipt

            parent = value(
                await client.call_tool(
                    "stories_add_comment",
                    {
                        "story_id": ids["story_id"],
                        "revision_id": ids["revision_id"],
                        "text": "Agent clarification",
                        "request_id": "agent-note",
                    },
                )
            )
            response = {
                "story_id": ids["story_id"],
                "annotation_id": parent["annotation_id"],
                "text": "User response",
                "request_id": "response",
                "author": "user",
            }
            reply = value(await client.call_tool("stories_respond", response))
            assert reply["status"] == "queued"
            assert api.get_operation(reply["operation_id"])["state"] == "succeeded"
            assert value(await client.call_tool("stories_respond", response)) == reply
            assert len(calls) == 2
            assert api.get_story(ids["story_id"])["feedback_grant"]["used"] == 2

    anyio.run(run)


def test_cancel_operation_keeps_dashboard_identity_without_changing_payload(tmp_path):
    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path, execution="queued")
        sid = ids["story_id"]
        api.grant_feedback(sid, {}, "cancel-grant")
        receipt = api.add_comment(sid, ids["revision_id"], "Queued edit", "cancel-note")
        args = {"operation_id": receipt["operation_id"]}
        assert api.get_operation(args["operation_id"])["state"] == "queued"
        async with Client(create_server(api), extensions=[APPS]) as client:
            before = await client.call_tool("stories_get_operation", args)
            assert value(before)["state"] == "queued"
            cancelled = await client.call_tool("stories_cancel_operation", args)
            assert not cancelled.is_error, cancelled.content
            assert cancelled.meta == before.meta
            assert cancelled.meta["amplifier/presentationId"] == "stories:story:" + sid
            assert cancelled.structured_content == {
                "operation": "cancel_operation",
                "story_id": None,
                "result": {
                    "status": "cancelled",
                    "cleanup": "complete",
                    "notice": "Late commits are prohibited; provider spending already in flight may occur.",
                },
            }
            repeated = await client.call_tool("stories_cancel_operation", args)
            assert repeated.structured_content == cancelled.structured_content
            assert repeated.meta == cancelled.meta
            assert json.loads(cancelled.content[0].text) == cancelled.structured_content
            after = await client.call_tool("stories_get_operation", args)
            assert value(after)["state"] == "cancelled"
            assert after.meta == cancelled.meta
            for name in ("stories_cancel_operation", "stories_get_operation"):
                missing = await client.call_tool(name, {"operation_id": "missing"})
                assert missing.is_error
                assert not (missing.meta or {}).get("amplifier/presentationId")

    anyio.run(run)


def test_cancel_metadata_lookup_failure_preserves_success(tmp_path, monkeypatch):
    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path, execution="queued")
        sid = ids["story_id"]
        api.grant_feedback(sid, {}, "cancel-grant")
        receipt = api.add_comment(sid, ids["revision_id"], "Queued edit", "cancel-note")
        get_operation = api.get_operation

        def unavailable(operation_id):
            raise StoriesError("not_found", "Retained operation unavailable.")

        monkeypatch.setattr(api, "get_operation", unavailable)
        async with Client(create_server(api), extensions=[APPS]) as client:
            result = await client.call_tool(
                "stories_cancel_operation", {"operation_id": receipt["operation_id"]}
            )
            assert value(result)["status"] == "cancelled"
            assert not (result.meta or {}).get("amplifier/presentationId")
            assert get_operation(receipt["operation_id"])["state"] == "cancelled"

    anyio.run(run)


def test_explicit_dashboard_identity_tracks_story_across_review_methods(tmp_path):
    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path)
        async with Client(create_server(api), extensions=[APPS]) as client:
            for name, args in [
                ("stories_get_story", {"story_id": ids["story_id"]}),
                ("stories_get_review_view", {"story_id": ids["story_id"]}),
            ]:
                result = await client.call_tool(name, args)
                assert not result.is_error, result.content
                assert result.meta["amplifier/presentationId"] == "stories:story:" + ids["story_id"]
            status = await client.call_tool("stories_status", {})
            assert not (status.meta or {}).get("amplifier/presentationId")
            rejected = await client.call_tool("stories_get_story", {"story_id": "missing"})
            assert rejected.is_error and not (rejected.meta or {}).get("amplifier/presentationId")
        other = fixture.seed(tmp_path / "independent")
        async with Client(create_server(Stories(tmp_path / "independent")), extensions=[APPS]) as client:
            result = await client.call_tool("stories_get_story", {"story_id": other["story_id"]})
            assert result.meta["amplifier/presentationId"] != "stories:story:" + ids["story_id"]

    anyio.run(run)
