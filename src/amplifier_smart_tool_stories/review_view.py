"""Durable review navigation, independent from choosing or accepting material."""

import copy
import json

from .artifacts import parse_html, validate_anchor
from .errors import require


class ReviewViewLibrary:
    @staticmethod
    def _review_view(story, view_id):
        require(
            isinstance(view_id, str) and 0 < len(view_id) <= 100, "Use a review view ID of 1–100 characters."
        )
        state = copy.deepcopy(
            story.get("review_views", {}).get(view_id)
            or {
                "view_id": view_id,
                "version": 0,
                "revision_id": story.get("selected_revision") or story.get("latest_revision"),
                "slide": 1,
                "comparison_revision": None,
                "panel_open": False,
                "anchor": {"kind": "story"},
                "export_format": "html",
                "sections": [],
                "native_context": {},
            }
        )

        # A panel may be opened before any revision exists. Its first material
        # should become visible even though that navigation state is already saved.
        if state["revision_id"] is None:
            state["revision_id"] = story.get("selected_revision") or story.get("latest_revision")
        return state

    def get_review_view(self, story_id, view_id="shared"):
        """Read durable revision focus, one-based slide, comparison, selection and panel state; no authority."""
        with self.store.transaction() as db:
            return self._review_view(self.store.get(db, "stories", story_id), view_id)

    def update_review_view(
        self,
        story_id,
        expected_version,
        request_id,
        view_id="shared",
        revision_id=None,
        slide=None,
        comparison_revision=None,
        panel_open=None,
        anchor=None,
        export_format=None,
        sections=None,
        native_context=None,
    ):
        """Update shared review navigation at an exact version; viewing never chooses, accepts or runs work.

        Read get_review_view first. Stale versions conflict; retry identical input with the same request_id.
        Empty comparison_revision clears comparison. Slides are one-based. Omitted fields stay unchanged.
        """
        require(
            type(expected_version) is int and expected_version >= 0, "expected_version must be nonnegative."
        )
        payload = [
            story_id,
            view_id,
            expected_version,
            revision_id,
            slide,
            comparison_revision,
            panel_open,
            anchor,
            export_format,
            sections,
            native_context,
        ]

        def action(db):
            story = self.store.get(db, "stories", story_id)
            state = self._review_view(story, view_id)
            require(
                state["version"] == expected_version,
                "Review view changed. Read get_review_view and reconcile before updating.",
                "view_conflict",
            )
            if revision_id is not None and revision_id != state["revision_id"]:
                self._revision(story, revision_id)
                state.update(revision_id=revision_id, slide=1, anchor={"kind": "story"})
            rev = self._revision(story, state["revision_id"]) if state["revision_id"] else None
            if slide is not None:
                require(
                    type(slide) is int
                    and 1 <= slide <= max(1, len(parse_html(rev["html"]).select(".slide")) if rev else 1),
                    "Slide is outside this exact revision.",
                )
                state["slide"] = slide
            if comparison_revision is not None:
                if comparison_revision:
                    self._revision(story, comparison_revision)
                state["comparison_revision"] = comparison_revision or None
            if panel_open is not None:
                require(type(panel_open) is bool, "panel_open must be a boolean.")
                state["panel_open"] = panel_open
            if anchor is not None:
                require(rev is not None, "A revision is required for a review target.")
                state["anchor"] = validate_anchor(rev["html"], anchor, rev.get("assets", []))
            if export_format is not None:
                require(export_format in {"html", "zip", "pdf", "docx"}, "Unknown export format.")
                state["export_format"] = export_format
            if sections is not None:
                require(
                    isinstance(sections, list)
                    and len(sections) <= 4
                    and all(
                        isinstance(s, str) and s in {"sources", "grant", "export", "work"} for s in sections
                    ),
                    "Unknown review panel section.",
                )
                state["sections"] = sorted(set(sections))
            if native_context is not None:
                require(
                    isinstance(native_context, dict)
                    and set(native_context)
                    <= {
                        "document_view",
                        "composer_open",
                        "draft_id",
                        "active_annotation",
                        "review_visible",
                        "comparison_ids",
                        "pending",
                        "narration",
                        "details_open",
                        "comparison_open",
                        "revision_comments",
                    }
                    and len(json.dumps(native_context, allow_nan=False)) <= 64000,
                    "Invalid or oversized native review context.",
                )
                for field in ("composer_open", "review_visible", "details_open", "comparison_open"):
                    require(
                        field not in native_context or type(native_context[field]) is bool,
                        f"{field} must be boolean.",
                    )
                for field in ("draft_id", "active_annotation"):
                    value = native_context.get(field)
                    require(
                        value is None or isinstance(value, str) and len(value) <= 200, f"Invalid {field}."
                    )
                document = native_context.get("document_view")
                if document is not None:
                    require(
                        isinstance(document, dict)
                        and set(document) <= {"mode", "zoom", "fit", "passage"}
                        and document.get("mode", "continuous") in {"continuous", "paginated"}
                        and type(document.get("zoom", 1)) in (int, float)
                        and 0.35 <= document.get("zoom", 1) <= 2
                        and type(document.get("fit", False)) is bool,
                        "Invalid document view.",
                    )
                comparisons = native_context.get("comparison_ids", [])
                require(
                    isinstance(comparisons, list) and len(comparisons) <= 2, "Compare at most two revisions."
                )
                for target in comparisons:
                    self._revision(story, target)
                comments = native_context.get("revision_comments", {})
                require(isinstance(comments, dict), "Invalid revision comment context.")
                for target, comment in comments.items():
                    material = self._revision(story, target)
                    require(
                        isinstance(comment, dict)
                        and set(comment) == {"anchor", "draft_id", "active_annotation", "composer_open"}
                        and type(comment["composer_open"]) is bool
                        and all(
                            comment[field] is None
                            or isinstance(comment[field], str)
                            and len(comment[field]) <= 200
                            for field in ("draft_id", "active_annotation")
                        ),
                        "Invalid revision comment context.",
                    )
                    checked_anchor = validate_anchor(
                        material["html"], comment["anchor"], material.get("assets", [])
                    )
                    if comment["draft_id"] is not None:
                        draft = story["drafts"].get(comment["draft_id"])
                        require(
                            draft is not None
                            and draft["revision_id"] == target
                            and draft["anchor"] == checked_anchor,
                            "Retained comment draft must match its exact revision and anchor.",
                        )
                    if comment["active_annotation"] is not None:
                        require(
                            any(
                                note["id"] == comment["active_annotation"]
                                and note["revision_id"] == target
                                and note["anchor"] == checked_anchor
                                for note in story["annotations"]
                            ),
                            "Retained comment thread must match its exact revision and anchor.",
                        )
                pending = native_context.get("pending", {})
                require(isinstance(pending, dict) and len(pending) <= 12, "Invalid pending review intents.")
                for intent in pending.values():
                    require(
                        isinstance(intent, dict)
                        and set(intent) == {"payload", "request_id"}
                        and isinstance(intent["request_id"], str)
                        and 0 < len(intent["request_id"]) <= 200
                        and isinstance(intent["payload"], dict)
                        and intent["payload"].get("story_id") == story_id,
                        "Pending intents must retain this exact story, payload and request identity.",
                    )
                narration = native_context.get("narration", {})
                require(isinstance(narration, dict), "Invalid narration draft context.")
                for target, draft in narration.items():
                    self._revision(story, target)
                    require(
                        isinstance(draft, dict)
                        and set(draft)
                        <= {
                            "notes",
                            "script_id",
                            "guidance",
                            "duration",
                            "operation",
                            "writing_operation",
                            "writing_draft",
                        }
                        and isinstance(draft.get("notes", []), list)
                        and all(isinstance(text, str) for text in draft.get("notes", [])),
                        "Invalid narration draft.",
                    )
                    for field, table, kind in (
                        ("operation", "operations", "narration"),
                        ("writing_operation", "operations", "prepare_narration"),
                        ("script_id", "narration_scripts", None),
                    ):
                        reference = draft.get(field)
                        if reference is None:
                            continue
                        require(
                            isinstance(reference, str) and 0 < len(reference) <= 200,
                            f"Retained narration reference {field} must be an identity or null.",
                        )
                        record = self.store.get(db, table, reference)
                        require(
                            record["story_id"] == story_id
                            and record["revision_id"] == target
                            and (kind is None or record["kind"] == kind),
                            f"Retained narration reference {field} must match its exact story, revision and kind.",
                        )
                # Context is inert caller data: never dispatch a retained request.
                # Explicit UI retry still crosses the original public mutation.
                state["native_context"] = copy.deepcopy(native_context)
            state["version"] += 1
            story.setdefault("review_views", {})[view_id] = state
            self.store.put(db, "stories", story)
            self.store.event(db, story_id, "review_view_changed", view_id=view_id, version=state["version"])
            return copy.deepcopy(state)

        return self._mutation(request_id, "update_review_view", payload, action)
