"""Shared story state. Adapters call these methods; they never edit state directly."""

import copy
import inspect
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from .artifacts import digest, evidence_checked, parse_html, preview, validate_anchor
from .errors import StoriesError, require
from .media import MediaLibrary, bindings, select, warnings_for
from .provider_jobs import ProviderJobLibrary, active_jobs
from .review_view import ReviewViewLibrary
from .scripts import ScriptLibrary
from .speech import NarrationLibrary
from .store import Store, identity, now
from .storyboard_library import StoryboardLibrary


class Stories(
    StoryboardLibrary, MediaLibrary, NarrationLibrary, ScriptLibrary, ReviewViewLibrary, ProviderJobLibrary
):
    def __init__(
        self,
        storage=None,
        *,
        model_env=False,
        provider=None,
        model=None,
        execution="queued",
        intelligence=None,
    ):
        self.store = Store(storage or os.environ.get("STORIES_STORE") or Path.home() / ".local/share/stories")
        from .providers import ProviderConfig

        self.config = ProviderConfig(provider, model)
        self._feedback_provider_override = False
        self.model_env = model_env
        require(execution in {"queued", "background", "in_process"}, "Unknown execution mode.")
        self.execution = execution
        self.intelligence = intelligence

    def _mutation(self, request_id, kind, payload, action):
        require(isinstance(request_id, str) and 0 < len(request_id) <= 200, "A request_id is required.")
        fingerprint = digest(json.dumps([kind, payload], sort_keys=True, allow_nan=False))
        with self.store.transaction() as db:
            prior = db.execute("SELECT digest,result FROM requests WHERE id=?", (request_id,)).fetchone()
            if prior:
                require(
                    prior[0] == fingerprint,
                    "request_id already used with different input.",
                    "request_conflict",
                )
                return json.loads(prior[1])
            if kind in {
                "generate",
                "generate_storyboard",
                "prepare_narration",
                "generate_narration",
                "add_comment",
                "respond",
                "answer_question",
            }:
                require(
                    not active_jobs(db),
                    "Provider setup is running; your draft remains unsubmitted.",
                    "provider_busy",
                )
            result = action(db)
            db.execute("INSERT INTO requests VALUES (?,?,?)", (request_id, fingerprint, json.dumps(result)))
        # Only the first accepted mutation may dispatch. Exact receipt retries never launch work.
        if result.get("operation_id"):
            self._dispatch(result["operation_id"])
        return result

    def _dispatch(self, operation_id):
        if self.execution == "in_process":
            self.run_operation(operation_id)
        elif self.execution == "background":
            argv = [
                sys.executable,
                "-m",
                "amplifier_smart_tool_stories.worker",
                str(self.store.path),
                operation_id,
            ]
            if self.model_env:
                argv.append("--model-env")
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    @staticmethod
    def _sources(sources):
        require(isinstance(sources, list) and len(sources) <= 50, "Supply at most 50 source objects.")
        result, seen = [], set()
        for source in sources:
            require(isinstance(source, dict), "Source must be an object.")
            require(set(source) <= {"id", "name", "content", "kind", "attribution"}, "Unknown source fields.")
            sid, content = source.get("id"), source.get("content")
            require(
                isinstance(sid, str) and sid and sid not in seen,
                "Source IDs must be unique nonempty strings.",
            )
            require(isinstance(content, str) and content.strip(), "Source content must be nonempty text.")
            require(
                source.get("kind", "source") in {"source", "summary", "hypothesis", "preference"},
                "Unknown source kind.",
            )
            require(isinstance(source.get("attribution", ""), str), "Attribution must be text.")
            seen.add(sid)
            result.append(
                {
                    "id": sid,
                    "name": source.get("name", sid),
                    "content": content,
                    "sha256": digest(content),
                    **{key: source[key] for key in ("kind", "attribution") if key in source},
                }
            )
        require(sum(len(s["content"].encode()) for s in result) <= 1_000_000, "Sources exceed 1 MB.")
        return result

    @staticmethod
    def _grant(grant):
        require(isinstance(grant, dict), "Grant must be an object.")
        require(
            set(grant) <= {"max_operations", "timeout_seconds", "max_output_tokens", "expires_at"},
            "Unknown grant fields.",
        )
        value = {
            "max_operations": 1,
            "timeout_seconds": 180,
            "max_output_tokens": 12000,
            "expires_at": now() + 3600,
            **grant,
        }
        for key, low, high in [
            ("max_operations", 1, 100),
            ("timeout_seconds", 1, 900),
            ("max_output_tokens", 128, 24000),
        ]:
            require(type(value[key]) is int and low <= value[key] <= high, f"Invalid {key}.")
        require(
            type(value["expires_at"]) in (int, float) and now() < value["expires_at"] < now() + 86401,
            "Grant expires_at must be within the next 24 hours.",
        )
        return value

    @staticmethod
    def _revision(story, revision_id):
        for revision in story["revisions"]:
            if revision["id"] == revision_id:
                return revision
        raise StoriesError("not_found", "Revision does not belong to this story.")

    def _new_revision(
        self,
        story,
        html,
        base=None,
        evidence=None,
        limitations=None,
        origin="imported",
        document=None,
        assets=None,
    ):
        if document is not None:
            from .documents import checked, render_document

            document = checked(document, evidence or [])
            require(html == render_document(document, evidence or []), "Document and HTML disagree.")
        if assets is None:
            assets = self._revision(story, base).get("assets", []) if base else story.get("assets", [])
        bindings(html, assets, strict=bool(assets) or origin == "model")
        parse_html(html)
        evidence = evidence_checked(evidence or [], story["sources"])
        revision = {
            "id": identity("rev"),
            "base_revision": base,
            "created_at": now(),
            "html": html,
            "sha256": digest(html),
            "assets": copy.deepcopy(assets),
            "delivery_sha256": digest(json.dumps([html, assets], sort_keys=True)),
            "media_warnings": warnings_for(assets),
            "format": "html",
            "kind": "document" if document is not None else "presentation",
            **({"document": document} if document is not None else {}),
            "origin": origin,
            "evidence": evidence,
            "limitations": limitations or [],
            "review": {
                "structural": "passed: nonempty HTML document",
                "evidence_references": "passed: exact source quotes" if evidence else "not_performed",
                "semantic": "not_performed",
                "visual": "not_performed",
                **(
                    {"media_playback": "not_performed: static review inspects posters, not playback or audio"}
                    if any(a["mime_type"].startswith("video/") for a in assets)
                    else {}
                ),
            },
        }
        story["revisions"].append(revision)
        story["latest_revision"] = revision["id"]
        if story["selected_revision"] is None:
            story["selected_revision"] = revision["id"]
        return revision

    def create_story(
        self,
        title,
        html,
        request_id,
        sources=None,
        purpose="Review supplied material",
        audience="Reader",
        document=None,
        asset_ids=None,
    ):
        """Import HTML and optional retained assets for isolated review; original markup is retained."""
        require(isinstance(title, str) and title.strip() and len(title) <= 300, "Supply a short title.")
        require(isinstance(purpose, str) and isinstance(audience, str), "Purpose and audience must be text.")
        supplied = self._sources(sources or [])
        if document is not None:
            from .documents import render_document

            html = render_document(document)
        parse_html(html)

        def action(db):
            assets = select(db, asset_ids or [])
            require(not assets or document is None, "Media composition currently supports presentations.")
            story = {
                "id": identity("story"),
                "title": title,
                "purpose": purpose,
                "audience": audience,
                "created_at": now(),
                "sources": supplied,
                "assets": assets,
                "revisions": [],
                "annotations": [],
                "drafts": {},
                "selected_revision": None,
                "latest_revision": None,
                "feedback_grant": None,
            }
            rev = self._new_revision(
                story, html, limitations=["Imported content has not been fact-checked."], document=document
            )
            story["kind"] = rev["kind"]
            self.store.put(db, "stories", story)
            self.store.event(db, story["id"], "story_created", revision_id=rev["id"])
            return {"status": "succeeded", "story_id": story["id"], "revision_id": rev["id"]}

        return self._mutation(
            request_id,
            "create_story",
            [title, document if document is not None else html, supplied, purpose, audience]
            + ([asset_ids] if asset_ids else []),
            action,
        )

    def create_document(
        self, title, document, request_id, sources=None, purpose="Review supplied material", audience="Reader"
    ):
        """Import document structure without model use; reviewed facts and citations require generation."""
        return self.create_story(title, "", request_id, sources, purpose, audience, document=document)

    def list_stories(self):
        """List retained story identities without artifacts or model use."""
        with self.store.transaction() as db:
            return [
                {k: s[k] for k in ("id", "title", "selected_revision", "latest_revision")}
                for (raw,) in db.execute("SELECT data FROM stories")
                for s in [json.loads(raw)]
            ]

    def get_story(self, story_id):
        """Read shared state, annotation outcomes, saved drafts and revision summaries."""
        with self.store.transaction() as db:
            story = self.store.get(db, "stories", story_id)
        for rev in story["revisions"]:
            rev.pop("html")
            rev.pop("document", None)
            rev.pop("storyboard", None)
        return story

    def get_revision(self, story_id, revision_id):
        """Read exact retained HTML, evidence and checks for a named revision."""
        with self.store.transaction() as db:
            return self._revision(self.store.get(db, "stories", story_id), revision_id)

    def get_preview(self, story_id, revision_id):
        """Return isolated HTML, retained media references and selectable elements; arbitrary resources are suppressed."""
        rev = self.get_revision(story_id, revision_id)
        html, anchors = preview(rev["html"], rev.get("assets", []))
        return {
            "revision_id": revision_id,
            "html": html,
            "elements": anchors,
            "assets": rev.get("assets", []),
            "media_warnings": rev.get("media_warnings", []),
            "kind": rev.get("kind", "presentation"),
            "limitations": [
                "Source scripts, forms and unregistered resources are disabled. Video playback is not a static-review pass.",
                "Text offsets count Unicode characters within an identified element.",
            ],
        }

    def select_revision(self, story_id, revision_id, request_id):
        """Explicitly select an existing revision; never implies approval or model work."""

        def action(db):
            story = self.store.get(db, "stories", story_id)
            self._revision(story, revision_id)
            story["selected_revision"] = revision_id
            self.store.put(db, "stories", story)
            self.store.event(db, story_id, "revision_selected", revision_id=revision_id)
            return {"status": "succeeded", "revision_id": revision_id}

        return self._mutation(request_id, "select_revision", [story_id, revision_id], action)

    def grant_feedback(self, story_id, grant, request_id):
        """Authorize a finite number of future user-comment responses with this provider; no spending now."""
        checked = self._grant(grant)

        def action(db):
            story = self.store.get(db, "stories", story_id)
            story["feedback_grant"] = {**checked, "used": 0, "provider": self.config.public()}
            self.store.put(db, "stories", story)
            self.store.event(db, story_id, "feedback_authorized")
            return {"status": "succeeded", "grant": story["feedback_grant"]}

        return self._mutation(request_id, "grant_feedback", [story_id, grant, self.config.public()], action)

    def _queue(self, db, story, kind, grant, revision_id=None, annotation_id=None):
        require(grant["expires_at"] > now(), "Execution authority expired.", "authority_expired")
        operation = {
            "id": identity("op"),
            "story_id": story["id"],
            "kind": kind,
            "revision_id": revision_id,
            "annotation_id": annotation_id,
            "state": "queued",
            "created_at": now(),
            "grant": grant,
            "provider": self.config.public()
            if self._feedback_provider_override
            else grant.get("provider", self.config.public()),
            "result": None,
            "error": None,
        }
        if story.get("kind") == "storyboard":
            operation.update(brief_id=story["brief_id"], direction_count=1)
        self.store.put(db, "operations", operation)
        self.store.event(db, story["id"], "operation_queued", operation_id=operation["id"])
        return operation["id"]

    def add_comment(self, story_id, revision_id, text, request_id, anchor=None, author="user"):
        """Submit anchored feedback. Caller highlights never spend; user comments queue only when execution can use authority."""
        require(author in {"user", "agent"}, "Author must be user or agent.")
        require(
            isinstance(text, str) and 0 < len(text.strip()) <= 12000,
            "Comment must contain 1–12000 characters.",
        )
        target = anchor or {"kind": "story"}

        def action(db):
            story = self.store.get(db, "stories", story_id)
            rev = self._revision(story, revision_id)
            checked = validate_anchor(rev["html"], target, rev.get("assets", []))
            note = {
                "id": identity("note"),
                "revision_id": revision_id,
                "anchor": checked,
                "author": author,
                "text": text,
                "created_at": now(),
                "responses": [],
                "status": "recorded",
                "operation_id": None,
                "result_revision": None,
            }
            grant = story["feedback_grant"]
            if author == "user":
                if grant and grant["expires_at"] > now() and grant["used"] < grant["max_operations"]:
                    # Queued work may be claimed later by a model-enabled worker. Immediate
                    # execution without model access, however, is known to fail, so retain
                    # the submission without consuming its existing grant.
                    if self.execution == "queued" or self.model_env or self.intelligence is not None:
                        grant["used"] += 1
                        note["operation_id"] = self._queue(
                            db, story, "comment", copy.deepcopy(grant), revision_id, note["id"]
                        )
                        note["status"] = "queued"
                    else:
                        note["status"] = "awaiting_model_access"
                else:
                    note["status"] = "awaiting_authority"
            story["annotations"].append(note)
            self.store.put(db, "stories", story)
            self.store.event(
                db, story_id, "comment_submitted", annotation_id=note["id"], revision_id=revision_id
            )
            return {
                "status": note["status"],
                "annotation_id": note["id"],
                "operation_id": note["operation_id"],
            }

        return self._mutation(
            request_id, "add_comment", [story_id, revision_id, text, target, author], action
        )

    def respond(self, story_id, annotation_id, text, request_id, author="user"):
        """Continue an annotation on its exact target; author=agent records a non-spending caller note."""
        story = self.get_story(story_id)
        note = next((n for n in story["annotations"] if n["id"] == annotation_id), None)
        require(note is not None, "Unknown annotation.")
        return self.add_comment(story_id, note["revision_id"], text, request_id, note["anchor"], author)

    def answer_question(self, operation_id, text, grant, request_id):
        """Answer a pending generation question with explicit bounded authority; retain its story and question chain."""
        require(
            isinstance(text, str) and 0 < len(text.strip()) <= 12000,
            "Supply an answer under 12000 characters.",
        )
        checked = self._grant(grant)

        def action(db):
            prior = self.store.get(db, "operations", operation_id)
            require(not prior.get("answered_by"), "Question already answered.", "question_already_answered")
            require(
                prior["state"] == "needs_input" and prior["kind"] == "generate",
                "Operation is not a pending generation question.",
                "question_not_pending",
            )
            story = self.store.get(db, "stories", prior["story_id"])
            child_id = self._queue(db, story, "generate", checked)
            child = self.store.get(db, "operations", child_id)
            child["continuation"] = prior.get("continuation", []) + [
                {"operation_id": operation_id, "question": prior["result"]["message"], "answer": text}
            ]
            child["provider"] = prior["provider"]
            for key in ("direction_count", "brief_id"):
                if key in prior:
                    child[key] = prior[key]
            self.store.put(db, "operations", child)
            prior["answered_by"] = child_id
            prior["state"] = "continued"
            self.store.put(db, "operations", prior)
            self.store.event(
                db,
                story["id"],
                "question_answered",
                operation_id=operation_id,
                continuation_operation_id=child_id,
            )
            return {
                "status": "queued",
                "story_id": story["id"],
                "operation_id": child_id,
                "question_operation_id": operation_id,
            }

        return self._mutation(request_id, "answer_question", [operation_id, text, grant], action)

    def accept_revision(self, story_id, revision_id, request_id):
        """Record explicitly conveyed human acceptance of this exact revision; no model or publication authority."""

        def action(db):
            story = self.store.get(db, "stories", story_id)
            revision = self._revision(story, revision_id)
            acceptance = {
                "revision_id": revision_id,
                "artifact_sha256": revision["sha256"],
                "delivery_sha256": revision.get("delivery_sha256", revision["sha256"]),
                "accepted_at": now(),
                "request_id": request_id,
            }
            story.setdefault("acceptances", []).append(acceptance)
            self.store.put(db, "stories", story)
            self.store.event(db, story_id, "revision_accepted", **acceptance)
            return {"status": "succeeded", "acceptance": acceptance}

        return self._mutation(request_id, "accept_revision", [story_id, revision_id], action)

    def save_draft(self, story_id, revision_id, draft_id, sequence, text, anchor=None, expected_version=None):
        """Save inert text with content CAS. Pass the observed draft version (zero if absent).

        Exact retries return the accepted version. Legacy sequence-only writes remain
        supported only for drafts not yet protected by CAS; they cannot bypass it.
        """
        require(isinstance(draft_id, str) and 0 < len(draft_id) <= 200, "Supply a draft identity.")
        require(type(sequence) is int and sequence >= 0, "Draft sequence must be a nonnegative integer.")
        require(isinstance(text, str) and len(text) <= 12000, "Draft is too long.")
        with self.store.transaction() as db:
            story = self.store.get(db, "stories", story_id)
            rev = self._revision(story, revision_id)
            checked = validate_anchor(rev["html"], anchor or {"kind": "story"}, rev.get("assets", []))
            old = story["drafts"].get(draft_id)
            version = old.get("version", 0) if old else 0
            if expected_version is not None:
                require(type(expected_version) is int and expected_version >= 0, "Invalid draft version.")
                if (
                    old
                    and old.get("cas")
                    and version == expected_version + 1
                    and old["sequence"] == sequence
                    and old["text"] == text
                    and old["anchor"] == checked
                    and old["revision_id"] == revision_id
                ):
                    return {"status": "saved", "sequence": sequence, "version": version}
                require(
                    version == expected_version,
                    "Draft changed in another view. Retain your text and reopen to reconcile.",
                    "draft_conflict",
                )
            else:
                require(
                    not old or not old.get("cas"),
                    "This shared draft requires its observed version.",
                    "draft_conflict",
                )
            if expected_version is None and old and old["sequence"] >= sequence:
                return {"status": "stale", "draft": old}
            story["drafts"][draft_id] = {
                "revision_id": revision_id,
                "anchor": checked,
                "text": text,
                "sequence": sequence,
                "saved_at": now(),
                "version": version + 1,
                "cas": expected_version is not None,
            }
            self.store.put(db, "stories", story)
            return {"status": "saved", "sequence": sequence, "version": version + 1}

    def generate(
        self, title, purpose, audience, sources, grant, request_id, kind="presentation", asset_ids=None
    ):
        """Generate a presentation or structured document; one repair, up to five presentation or eleven document model calls."""
        require(
            isinstance(kind, str) and kind in {"presentation", "document"},
            "Kind must be presentation or document.",
        )
        require(
            all(isinstance(x, str) and x.strip() for x in (title, purpose, audience)),
            "Title, purpose, audience required.",
        )
        supplied = self._sources(sources)
        require(supplied, "Generation needs at least one supplied source.")
        checked = self._grant(grant)

        def action(db):
            assets = select(db, asset_ids or [])
            require(
                not assets or kind == "presentation", "Media composition currently supports presentations."
            )
            story = {
                "id": identity("story"),
                "title": title,
                "kind": kind,
                "purpose": purpose,
                "audience": audience,
                "created_at": now(),
                "sources": supplied,
                "assets": assets,
                "revisions": [],
                "annotations": [],
                "drafts": {},
                "selected_revision": None,
                "latest_revision": None,
                "feedback_grant": None,
            }
            op = self._queue(db, story, "generate", checked)
            self.store.put(db, "stories", story)
            return {"status": "queued", "story_id": story["id"], "operation_id": op}

        return self._mutation(
            request_id,
            "generate",
            [title, purpose, audience, supplied, grant, self.config.public()]
            + ([kind] if kind != "presentation" else [])
            + ([asset_ids] if asset_ids else []),
            action,
        )

    def get_operation(self, operation_id):
        """Read status only. Interrupted work is never implicitly restarted."""
        with self.store.transaction() as db:
            op = self.store.get(db, "operations", operation_id)
        if op["state"] == "running" and now() > op["deadline"]:
            op["state"] = "interrupted"
            op["error"] = {
                "code": "completion_uncertain",
                "message": "Worker exceeded its deadline; cancel before new work.",
            }
        return op

    def cancel_operation(self, operation_id):
        """Cancel queued/running work and prevent late commits; retained revisions are unaffected."""
        with self.store.transaction() as db:
            op = self.store.get(db, "operations", operation_id)
            if op["state"] in {"queued", "running"}:
                op["cleanup"] = "complete" if op["state"] == "queued" else "pending"
                op["state"] = "cancelled"
                if op.get("narration_id"):
                    narration = self.store.get(db, "narrations", op["narration_id"])
                    narration["state"] = "cancelled"
                    self.store.put(db, "narrations", narration)
                self.store.put(db, "operations", op)
                story = self.store.get(db, "stories", op["story_id"])
                for note in story["annotations"]:
                    if note["operation_id"] == operation_id:
                        note["status"] = "cancelled"
                self.store.put(db, "stories", story)
                self.store.event(db, op["story_id"], "operation_cancelled", operation_id=operation_id)
            return {
                "status": op["state"],
                "cleanup": op.get("cleanup", "complete"),
                "notice": "Late commits are prohibited; provider spending already in flight may occur.",
            }

    def run_operation(self, operation_id):
        """Execute one queued operation once. Requires model_env or an explicitly injected intelligence adapter."""
        if self.get_operation(operation_id)["kind"] == "narration":
            from .speech import run_narration

            return run_narration(self, operation_id)
        with self.store.transaction() as db:
            op = self.store.get(db, "operations", operation_id)
            if op["state"] != "queued":
                return op
            op.update(
                state="running",
                started_at=now(),
                deadline=min(now() + op["grant"]["timeout_seconds"], op["grant"]["expires_at"]),
            )
            self.store.put(db, "operations", op)
            story = self.store.get(db, "stories", op["story_id"])
            for note in story["annotations"]:
                if note["operation_id"] == operation_id:
                    note["status"] = "running"
            self.store.put(db, "stories", story)
        try:
            require(
                self.model_env or self.intelligence is not None,
                "Model access was not enabled.",
                "model_access_required",
            )
            require(op["deadline"] > now(), "Execution grant expired.", "authority_expired")
            if self.intelligence is not None:
                result = self.intelligence(story, op)
            else:
                from .intelligence import execute
                from .media import image_payload

                selected_assets = (
                    self._revision(story, op["revision_id"]).get("assets", [])
                    if op["revision_id"]
                    else story.get("assets", [])
                )
                with self.store.transaction() as db:
                    story["_media_images"] = image_payload(db, selected_assets)
                result = execute(story, op, lambda: self.get_operation(operation_id)["state"] == "cancelled")
            with self.store.transaction() as db:
                current = self.store.get(db, "operations", operation_id)
                if current["state"] != "running":
                    current.update(cleanup="complete", finished_at=now())
                    self.store.put(db, "operations", current)
                    return current
                require(
                    now() <= op["deadline"], "Operation exhausted its time allowance.", "execution_timeout"
                )
                story = self.store.get(db, "stories", op["story_id"])
                if story.get("kind") == "storyboard":
                    return self._commit_storyboards(db, story, current, result)
                if op["kind"] == "prepare_narration":
                    from .scripts import retain

                    script = retain(
                        self,
                        db,
                        story,
                        self._revision(story, op["revision_id"]),
                        result,
                        origin="model",
                        base_script_id=op.get("base_script_id"),
                        guidance=op["guidance"],
                        target_seconds=op["target_seconds"],
                    )
                    current.update(
                        state="succeeded",
                        finished_at=now(),
                        cleanup="complete",
                        result={"script_id": script["id"], "revision_id": op["revision_id"]},
                    )
                    self.store.put(db, "operations", current)
                    self.store.event(
                        db,
                        story["id"],
                        "operation_completed",
                        operation_id=operation_id,
                        script_id=script["id"],
                        revision_id=op["revision_id"],
                    )
                    return current
                require(
                    isinstance(result, dict) and result.get("action") in {"answer", "clarify", "revise"},
                    "Invalid structured model submission.",
                    "invalid_model_result",
                )
                require(
                    isinstance(result.get("message"), str) and result["message"].strip(),
                    "Missing response text.",
                )
                if op["kind"] == "generate":
                    require(
                        result["action"] in {"revise", "clarify"}, "Generation needs HTML or a clarification."
                    )
                from .accountability import validate_disclosures

                validate_disclosures(result, story, op)
                new_revision = None
                evidence = evidence_checked(result.get("evidence", []), story["sources"])
                if result["action"] == "revise":
                    from .quality import validate_record

                    if story.get("kind") == "document":
                        require(result.get("document") is not None, "Document structure is required.")
                    quality = result.get("quality_review")
                    if self.intelligence is None:
                        from .accountability import disclosure_hash

                        require(
                            isinstance(quality, dict)
                            and quality.get("disclosure_sha256") == disclosure_hash(result),
                            "Disclosure changed after review.",
                            "stale_review",
                        )
                    if self.intelligence is None or quality is not None:
                        validate_record(result.get("html"), quality)
                    require(
                        bool(evidence) or not story["sources"], "Revision with sources requires evidence."
                    )
                    limitations = result.get("limitations", [])
                    require(
                        isinstance(limitations, list) and all(isinstance(x, str) for x in limitations),
                        "Limitations must be text entries.",
                    )
                    rev = self._new_revision(
                        story,
                        result.get("html"),
                        op["revision_id"],
                        evidence,
                        limitations,
                        "model",
                        document=result.get("document"),
                    )
                    rev["changes"] = result.get("changes", {})
                    rev["calculations"] = result.get("calculations", [])
                    if quality is not None:
                        rev["quality_review"] = quality
                        rev["review"]["semantic"] = "passed: model review of source fidelity and narrative"
                        rev["review"]["visual"] = "passed: model review of static rendered pages"
                    new_revision = rev["id"]
                for note in story["annotations"]:
                    if note["id"] == op["annotation_id"]:
                        note["responses"].append(
                            {
                                "author": "stories",
                                "text": result["message"],
                                "at": now(),
                                "evidence": evidence,
                            }
                        )
                        note["status"] = "needs_input" if result["action"] == "clarify" else "answered"
                        note["result_revision"] = new_revision
                current.update(
                    state="needs_input" if result["action"] == "clarify" else "succeeded",
                    finished_at=now(),
                    cleanup="complete",
                    result={
                        "action": result["action"],
                        "message": result["message"],
                        "revision_id": new_revision,
                        "changes": result.get("changes", {}),
                        "calculations": result.get("calculations", []),
                        "provenance": result.get("provenance", {}),
                        "evidence": evidence,
                        "review_attempts": result.get("review_attempts", []),
                    },
                )
                self.store.put(db, "stories", story)
                self.store.put(db, "operations", current)
                self.store.event(
                    db,
                    story["id"],
                    "operation_completed",
                    operation_id=operation_id,
                    revision_id=new_revision,
                )
                return current
        except Exception as exc:
            error = (
                exc.public()["error"]
                if isinstance(exc, StoriesError)
                else {
                    "code": "execution_failed",
                    "message": f"Execution failed ({type(exc).__name__}).",
                    "remedy": "Check runtime/provider setup. No fallback or automatic retry was performed.",
                }
            )
            with self.store.transaction() as db:
                current = self.store.get(db, "operations", operation_id)
                if current["state"] == "running":
                    current.update(state="failed", error=error, finished_at=now(), cleanup="complete")
                    if hasattr(exc, "candidate"):
                        current["candidate"] = exc.candidate
                    self.store.put(db, "operations", current)
                    story = self.store.get(db, "stories", op["story_id"])
                    for note in story["annotations"]:
                        if note["operation_id"] == operation_id:
                            note["status"] = "failed"
                            note["error"] = error
                    self.store.put(db, "stories", story)
                    self.store.event(db, op["story_id"], "operation_failed", operation_id=operation_id)
                elif current["state"] == "cancelled":
                    current.update(cleanup="complete", finished_at=now())
                    self.store.put(db, "operations", current)
                return current

    def read_changes(self, story_id, after=0):
        """Read ordered changes since a cursor; never starts work. Events are retained without expiry."""
        require(type(after) is int and after >= 0, "after must be a nonnegative sequence.")
        with self.store.transaction() as db:
            self.store.get(db, "stories", story_id)
            rows = db.execute(
                "SELECT seq,data FROM events WHERE story_id=? AND seq>? ORDER BY seq LIMIT 500",
                (story_id, after),
            ).fetchall()
        return {
            "changes": [{"sequence": seq, **json.loads(raw)} for seq, raw in rows],
            "cursor": rows[-1][0] if rows else after,
            "history_gap": False,
        }

    def get_export(self, story_id, revision_id, format="html"):
        """Get HTML with embedded images, a portable ZIP, or document PDF/Word as base64 with delivery identity."""
        from .exports import artifact

        revision = self.get_revision(story_id, revision_id)
        with self.store.transaction() as db:
            from .media import load

            content = {a["id"]: load(db, a["id"])[1] for a in revision.get("assets", [])}
        return artifact(revision, format, content)

    def export(self, story_id, revision_id, output_path, format="html"):
        """Write the chosen revision in an explicit format, excluding annotations; never overwrite."""
        import base64

        path = Path(output_path).expanduser().resolve()
        require(not path.exists(), "Output already exists; choose a new destination.", "output_exists")
        result = self.get_export(story_id, revision_id, format)
        try:
            with path.open("xb") as file:
                file.write(base64.b64decode(result.pop("data_base64")))
        except FileExistsError:
            raise StoriesError("output_exists", "Output already exists; choose a new destination.") from None
        return {"status": "succeeded", "path": str(path), **result}

    def export_video(
        self,
        story_id,
        revision_id,
        output_path,
        slide_seconds=None,
        timeout_seconds=300,
        narration_id=None,
        delivery="embedded",
        pause_seconds=0.5,
    ):
        """Export slides as silent MP4, or use retained narration for embedded MP4 (default) or separate assets ZIP."""
        return self._export_video(
            story_id,
            revision_id,
            output_path,
            slide_seconds,
            timeout_seconds,
            narration_id,
            delivery,
            pause_seconds,
            record_path=True,
        )

    def _export_video(
        self,
        story_id,
        revision_id,
        output_path,
        slide_seconds=None,
        timeout_seconds=300,
        narration_id=None,
        delivery="embedded",
        pause_seconds=0.5,
        *,
        record_path,
    ):
        from .media import image_payload
        from .video import encode

        revision = self.get_revision(story_id, revision_id)
        with self.store.transaction() as db:
            media = image_payload(db, revision.get("assets", []))
        if narration_id:
            from .narrated_video import export

            narration = self.get_narration(story_id, narration_id)
            result = export(
                self,
                revision,
                media,
                narration,
                output_path,
                slide_seconds,
                pause_seconds,
                delivery,
                timeout_seconds,
            )
        else:
            require(delivery == "embedded", "Separate delivery requires retained narration.")
            result = encode(revision, media, output_path, slide_seconds, timeout_seconds)
        result["story_id"] = story_id
        with self.store.transaction() as db:
            self.store.event(
                db,
                story_id,
                "video_exported",
                **{k: v for k, v in result.items() if k != "story_id" and (record_path or k != "path")},
            )
        return result

    def get_video_export(
        self,
        story_id,
        revision_id,
        narration_id,
        delivery="embedded",
        pause_seconds=0.5,
        timeout_seconds=300,
    ):
        """Prepare path-free video bytes from exact retained narration; never synthesizes speech.

        Presentation sources only. Output is bounded to 128 MiB; use export_video
        with an explicit destination for larger files. Temporary files are removed.
        """
        import base64
        import tempfile

        require(narration_id, "Choose retained narration first.")
        with tempfile.TemporaryDirectory(dir=self.store.path) as folder:
            result = self._export_video(
                story_id,
                revision_id,
                str(Path(folder) / ("video.zip" if delivery == "separate" else "video.mp4")),
                narration_id=narration_id,
                delivery=delivery,
                pause_seconds=pause_seconds,
                timeout_seconds=timeout_seconds,
                record_path=False,
            )
            path = Path(result.pop("path"))
            require(
                path.stat().st_size <= 128 * 1024 * 1024,
                "Video exceeds the 128 MiB transfer limit; use export_video.",
                "transfer_limit",
            )
            raw = path.read_bytes()
        return {
            **result,
            "story_id": story_id,
            "revision_id": revision_id,
            "narration_id": narration_id,
            "data_base64": base64.b64encode(raw).decode(),
            "bytes": len(raw),
        }

    def storytelling_capabilities(self):
        """List supported writing approaches and their upstream mapping; generation selects relevant expertise from the request."""
        from .expertise import catalog

        return {
            "approaches": catalog(),
            "outputs": ["presentation", "document", "storyboard"],
            "selection": "Internal evidence planning; describe your purpose and audience.",
            "limits": "Supplied text only; no network research, publication or arbitrary file conversion.",
        }

    def provider_settings(self):
        """Read redacted provider configuration and setup instructions without booting a model."""
        from .providers import settings

        return settings(self.config)

    def configure_provider(self, provider, model=None):
        """Set provider/model for future operations and authorized feedback in this instance; existing operations and grant limits stay fixed."""
        from .providers import ProviderConfig

        with self.store.transaction() as db:
            require(not active_jobs(db), "Wait for provider setup to finish.", "provider_busy")
            self.config = ProviderConfig(provider, model, use_env=False)
            self._feedback_provider_override = True
        return self.config.public()

    def prepare_runtime(self):
        """Explicitly resolve and install Amplifier's runtime modules. Network and package writes are expected."""
        from .providers import prepare_runtime

        require(self.model_env, "Enable model_env for runtime preparation.", "model_access_required")
        return prepare_runtime(self.config)

    def test_provider(self, timeout_seconds=60):
        """Send one small model request through the selected Amplifier provider; model_env required."""
        require(self.model_env, "Enable model_env for a connection test.", "model_access_required")
        from .providers import test_provider

        return test_provider(self.config, timeout_seconds)

    def provider_models(self, provider=None, timeout_seconds=60):
        """Discover provider model IDs without generation; model_env and prepared runtime required."""
        require(self.model_env, "Enable model_env for provider discovery.", "model_access_required")
        from .providers import ProviderConfig, provider_models

        config = ProviderConfig(provider, use_env=False) if provider else self.config
        return provider_models(config, timeout_seconds)

    def provider_login(self, provider=None, timeout_seconds=300, on_progress=None):
        """Explicit ChatGPT/Copilot sign-in or API-key setup guidance; native caches own credentials. May fetch runtime modules."""
        require(self.model_env, "Enable model_env for provider login.", "model_access_required")
        from .providers import ProviderConfig, provider_login

        config = ProviderConfig(provider, use_env=False) if provider else self.config
        return provider_login(config, timeout_seconds, on_progress)

    def start_dashboard(self, story_id, revision_id=None):
        """Start an authenticated loopback viewer for one story, without opening a browser."""
        self.get_story(story_id)
        if revision_id:
            self.get_revision(story_id, revision_id)
        from .dashboard import start

        return start(self, story_id, revision_id)

    def stop_dashboard(self, service_id):
        """Stop an owned viewer and cancel its queued/running comment work; preserve all retained data."""
        from .dashboard import stop

        return stop(self, service_id)

    @staticmethod
    def manifest():
        """Return the machine-readable public capability catalog without opening a store or a model."""
        import yaml

        raw = files("amplifier_smart_tool_stories").joinpath("SMART_TOOL.md").read_text()
        _, header, body = raw.split("---", 2)
        return {
            **yaml.safe_load(header),
            "body": body.strip(),
            "capabilities": [
                {
                    "name": name.replace("_", "-"),
                    "description": getattr(Stories, name).__doc__,
                    "signature": str(inspect.signature(getattr(Stories, name))),
                    "intelligence": "model-backed"
                    if name
                    in {
                        "generate",
                        "generate_storyboard",
                        "prepare_narration",
                        "answer_question",
                        "run_operation",
                        "test_provider",
                    }
                    else "conditional"
                    if name in {"add_comment", "respond", "generate_narration", "start_provider_job"}
                    else "deterministic",
                }
                for name in CAPABILITIES
            ],
        }


CAPABILITIES = [
    "start_provider_job",
    "get_provider_job",
    "cancel_provider_job",
    "get_video_export",
    "prepare_narration",
    "get_narration_script",
    "list_narration_scripts",
    "save_narration_script",
    "get_speaker_notes",
    "list_narrations",
    "narration_settings",
    "configure_narration",
    "generate_narration",
    "get_narration",
    "get_narration_audio",
    "export_video",
    "manifest",
    "create_storyboard",
    "generate_storyboard",
    "revise_storyboard",
    "select_direction",
    "update_storyboard_brief",
    "get_comparison",
    "import_media",
    "resize_media",
    "get_media",
    "revise_media",
    "create_story",
    "create_document",
    "generate",
    "list_stories",
    "get_story",
    "get_revision",
    "get_preview",
    "select_revision",
    "get_review_view",
    "update_review_view",
    "grant_feedback",
    "add_comment",
    "respond",
    "answer_question",
    "accept_revision",
    "save_draft",
    "read_changes",
    "get_operation",
    "run_operation",
    "cancel_operation",
    "export",
    "get_export",
    "storytelling_capabilities",
    "provider_settings",
    "configure_provider",
    "prepare_runtime",
    "test_provider",
    "provider_models",
    "provider_login",
    "start_dashboard",
    "stop_dashboard",
]
