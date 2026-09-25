"""Direct, explicitly authorized speech APIs and retained slide or panel narration."""

import asyncio
import base64
import hashlib
import io
import json
import os
import wave

from .artifacts import parse_html
from .errors import StoriesError, require
from .store import identity, now

DEFAULTS = {
    "openai": {"model": "gpt-4o-mini-tts", "voice": "marin"},
    "gemini": {"model": "gemini-3.1-flash-tts-preview", "voice": "Kore"},
}
ENV = {"openai": ["OPENAI_API_KEY"], "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"]}


def fingerprint(text, config):
    return hashlib.sha256(json.dumps([text, config], sort_keys=True).encode()).hexdigest()


def credential(provider):
    return next((os.environ[k] for k in ENV[provider] if os.environ.get(k)), None)


def wav(pcm):
    require(
        isinstance(pcm, bytes) and 0 < len(pcm) <= 64 * 1024 * 1024 and len(pcm) % 2 == 0,
        "Speech must return nonempty 24 kHz mono 16-bit PCM within the 64 MiB per-clip budget.",
        "invalid_audio",
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return out.getvalue()


async def synthesize(text, config, timeout):
    """Single attempt; SDK retries disabled. Never import or initialize an agent."""
    key = credential(config["provider"])
    require(
        key,
        "Speech API key is missing; configure " + " or ".join(ENV[config["provider"]]),
        "speech_unavailable",
    )
    if config["provider"] == "openai":
        from openai import AsyncOpenAI

        async with AsyncOpenAI(
            api_key=key, base_url="https://api.openai.com/v1", max_retries=0, timeout=timeout
        ) as client:
            args = dict(model=config["model"], voice=config["voice"], input=text, response_format="pcm")
            if config["instructions"]:
                args["instructions"] = config["instructions"]
            result = await client.audio.speech.create(**args)
            return wav(result.content)
    from google import genai
    from google.genai import types

    options = types.HttpOptions(
        timeout=max(1, int(timeout * 1000)), retry_options=types.HttpRetryOptions(attempts=1)
    )
    async with genai.Client(api_key=key, http_options=options).aio as client:
        prompt = (
            "Read the following narration verbatim. " + config["instructions"] + "\n\nNarration:\n" + text
        )
        response = await client.models.generate_content(
            model=config["model"],
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config["voice"])
                    )
                ),
            ),
        )
        parts = [
            p.inline_data
            for c in response.candidates or []
            if c.content
            for p in c.content.parts or []
            if p.inline_data
        ]
        # MIME types and parameters are case-insensitive (RFC 2045); Gemini
        # currently returns e.g. "audio/l16; rate=24000; channels=1".
        mime = "".join((parts[0].mime_type or "").lower().split()) if len(parts) == 1 else ""
        require(
            mime.startswith("audio/l16") and "rate=24000" in mime.split(";"),
            "Gemini returned no supported 24 kHz PCM audio.",
            "invalid_audio",
        )
        return wav(parts[0].data)


def audio_record(db, key):
    row = db.execute("SELECT data,content FROM speech_audio WHERE id=?", (key,)).fetchone()
    if not row:
        return None
    meta, data = json.loads(row[0]), row[1]
    require(
        hashlib.sha256(data).hexdigest() == meta["sha256"],
        "Retained narration audio is corrupt.",
        "invalid_audio",
    )
    return meta, data


class NarrationLibrary:
    def narration_settings(self):
        """Read store-scoped speech settings and redacted credential presence without a provider call."""
        with self.store.transaction() as db:
            row = db.execute("SELECT data FROM narration_settings WHERE id='speech'").fetchone()
        return {
            "effective": json.loads(row[0])["config"] if row else None,
            "scope": "store",
            "providers": [
                {
                    "provider": p,
                    **d,
                    "credential_present": bool(credential(p)),
                    "speech_access": "not_tested",
                    "credential_env": ENV[p],
                }
                for p, d in DEFAULTS.items()
            ],
            "unsupported": ["anthropic", "chatgpt", "copilot"],
            "notice": "Speech uses the selected provider's paid API. Key presence does not establish model access. Voices are AI-generated.",
        }

    def configure_narration(self, provider, request_id, model=None, voice=None, instructions=""):
        """Persist speech settings separately from writing settings; does not synthesize or spend."""
        require(
            provider in DEFAULTS, "Choose openai or gemini for speech; chat sign-in is not a speech API key."
        )
        config = {
            "provider": provider,
            "model": model or DEFAULTS[provider]["model"],
            "voice": voice or DEFAULTS[provider]["voice"],
            "instructions": instructions,
        }
        require(
            all(
                isinstance(config[k], str) and config[k].strip() and len(config[k]) <= 200
                for k in ("model", "voice")
            ),
            "Model and voice must be nonempty strings up to 200 characters.",
        )
        require(
            isinstance(instructions, str) and len(instructions) <= 2000,
            "Delivery instructions must be at most 2000 characters.",
        )

        def action(db):
            self.store.put(db, "narration_settings", {"id": "speech", "config": config})
            return {"status": "succeeded", "effective": config, "scope": "store"}

        return self._mutation(request_id, "configure_narration", config, action)

    def generate_narration(
        self,
        story_id,
        revision_id,
        grant,
        request_id,
        notes=None,
        retry_uncertain=False,
        script_id=None,
        concurrency=3,
        source="presentation",
    ):
        """Queue bounded speech from presentation notes/scripts or exact storyboard panel narration."""
        rev = self.get_revision(story_id, revision_id)
        require(
            isinstance(source, str) and source in {"presentation", "storyboard_panels"},
            "Choose presentation or storyboard_panels source.",
        )
        panels = None
        if source == "storyboard_panels":
            require(rev.get("kind") == "storyboard", "storyboard_panels source requires a storyboard.")
            require(
                notes is None and script_id is None,
                "Panel narration uses retained panel text; do not supply notes or script_id.",
            )
            panels = rev["storyboard"]["panels"]
            missing = [p["id"] for p in panels if not p["narration"].strip()]
            require(not missing, "Provide nonempty narration for every panel; missing: " + ", ".join(missing))
        else:
            require(
                rev.get("kind") not in {"document", "storyboard"},
                "Presentation narration requires a presentation; use source=storyboard_panels for storyboards.",
            )
        slides = [] if panels is not None else parse_html(rev["html"]).select(".slide")
        script = None
        if script_id:
            require(notes is None, "Supply script_id or notes, not both.")
            script = self.get_narration_script(story_id, script_id)
            require(
                script["revision_id"] == revision_id and script["source_sha256"] == rev["sha256"],
                "Script belongs to another revision.",
                "stale_script",
            )
            notes = [s["text"] for s in script["slides"]]
        supplied = notes is not None
        if panels is not None:
            notes = [p["narration"] for p in panels]
        elif notes is None:
            notes = [
                "\n".join(n.get_text(" ", strip=True) for n in s.select(".notes,[data-speaker-notes]"))
                for s in slides
            ]
        require(
            isinstance(notes, list)
            and len(notes) == len(panels if panels is not None else slides)
            and len(notes) > 0
            and all(isinstance(n, str) and n.strip() and len(n) <= 4000 for n in notes),
            "Provide nonempty speaker notes for each slide (maximum 4000 characters each); notes are never invented during synthesis.",
        )
        require(
            type(concurrency) is int and 1 <= concurrency <= 8, "concurrency must be an integer from 1 to 8."
        )
        require(type(retry_uncertain) is bool, "retry_uncertain must be boolean.")
        require(
            isinstance(grant, dict) and set(grant) <= {"max_requests", "max_characters", "timeout_seconds"},
            "Unknown narration grant fields.",
        )
        checked = {"max_requests": 12, "max_characters": 24000, "timeout_seconds": 300, **grant}
        for key, top in [("max_requests", 100), ("max_characters", 200000), ("timeout_seconds", 900)]:
            require(
                type(checked[key]) is int and 1 <= checked[key] <= top,
                f"{key} must be an integer from 1 to {top}.",
            )

        def action(db):
            row = db.execute("SELECT data FROM narration_settings WHERE id='speech'").fetchone()
            require(
                row, "Configure narration provider, model and voice before synthesis.", "speech_unavailable"
            )
            config = json.loads(row[0])["config"]
            missing = {
                fingerprint(n, config): n for n in notes if not audio_record(db, fingerprint(n, config))
            }
            require(
                len(missing) <= checked["max_requests"]
                and sum(len(n) for n in missing.values()) <= checked["max_characters"],
                "Narration exceeds the granted requests or input characters.",
                "execution_limit",
            )
            nar = {
                "id": identity("narration"),
                "story_id": story_id,
                "revision_id": revision_id,
                "source_sha256": rev["sha256"],
                "settings": config,
                "notes": notes,
                "notes_origin": "retained_script"
                if script
                else "supplied_adaptation"
                if supplied
                else "revision_notes",
                "script_id": script_id,
                "script_sha256": script["sha256"] if script else None,
                "clips": [],
                "state": "queued",
            }
            if panels is not None:
                nar.update(
                    source=source,
                    notes_origin="storyboard_panels",
                    panel_ids=[p["id"] for p in panels],
                    direction_id=rev["direction_id"],
                )
            op = {
                "id": identity("op"),
                "story_id": story_id,
                "revision_id": revision_id,
                "annotation_id": None,
                "kind": "narration",
                "state": "queued",
                "created_at": now(),
                "grant": checked,
                "narration_id": nar["id"],
                "retry_uncertain": retry_uncertain,
                "concurrency": concurrency,
                "result": None,
                "error": None,
            }
            nar["operation_id"] = op["id"]
            self.store.put(db, "narrations", nar)
            self.store.put(db, "operations", op)
            self.store.event(db, story_id, "operation_queued", operation_id=op["id"])
            return {
                "status": "queued",
                "story_id": story_id,
                "operation_id": op["id"],
                "narration_id": nar["id"],
            }

        return self._mutation(
            request_id,
            "generate_narration",
            [story_id, revision_id, grant, notes, supplied, retry_uncertain]
            + ([script_id] if script_id else [])
            + ([{"concurrency": concurrency}] if concurrency != 3 else [])
            + ([{"source": source}] if source != "presentation" else []),
            action,
        )

    def get_speaker_notes(self, story_id, revision_id):
        """Read slide notes without creating, adapting or synthesizing text."""
        rev = self.get_revision(story_id, revision_id)
        return {
            "revision_id": revision_id,
            "notes": [
                "\n".join(n.get_text(" ", strip=True) for n in slide.select(".notes,[data-speaker-notes]"))
                for slide in parse_html(rev["html"]).select(".slide")
            ],
        }

    def list_narrations(self, story_id, revision_id=None):
        """List retained narration and operation identities for this story and optional revision."""
        self.get_story(story_id)
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT data FROM narrations WHERE json_extract(data, '$.story_id')=?", (story_id,)
            ).fetchall()
        return {
            "narrations": [
                self.get_narration(story_id, n["id"])
                for (data,) in rows
                if (n := json.loads(data)) and (revision_id is None or n["revision_id"] == revision_id)
            ]
        }

    def get_narration(self, story_id, narration_id):
        """Read notes, settings, progress and audio identities for retained narration without spending."""
        with self.store.transaction() as db:
            nar = self.store.get(db, "narrations", narration_id)
        require(nar["story_id"] == story_id, "Narration belongs to another story.")
        if nar.get("operation_id"):
            nar["state"] = self.get_operation(nar["operation_id"])["state"]
        return nar

    def get_narration_audio(self, story_id, narration_id, slide=None, panel_id=None):
        """Read a completed WAV by slide number or stable panel ID, including after partial failure."""
        nar = self.get_narration(story_id, narration_id)
        if nar.get("source") == "storyboard_panels":
            require(
                slide is None and isinstance(panel_id, str) and panel_id in nar["panel_ids"],
                "Supply a retained panel_id, not a slide number, for storyboard narration.",
            )
            clip = next((c for c in nar["clips"] if c["panel_id"] == panel_id), None)
        else:
            require(type(slide) is int and panel_id is None, "Supply an integer slide number, not panel_id.")
            clip = next((c for c in nar["clips"] if c["slide"] == slide), None)
        require(
            clip, "Panel audio is not available." if panel_id is not None else "Slide audio is not available."
        )
        with self.store.transaction() as db:
            pair = audio_record(db, clip["audio_id"])
        require(pair, "Retained audio is missing.", "missing_asset")
        result = {
            "audio": pair[0],
            "mime_type": "audio/wav",
            "data_base64": base64.b64encode(pair[1]).decode(),
        }
        if panel_id is not None:
            result.update(
                clip=clip,
                source=nar["source"],
                story_id=story_id,
                revision_id=nar["revision_id"],
                source_sha256=nar["source_sha256"],
                direction_id=nar["direction_id"],
            )
        return result


def run_narration(api, operation_id):
    with api.store.transaction() as db:
        op = api.store.get(db, "operations", operation_id)
        if op["state"] != "queued":
            return op
        op.update(
            state="running",
            started_at=now(),
            deadline=now() + op["grant"]["timeout_seconds"],
            requests_used=0,
            characters_used=0,
        )
        api.store.put(db, "operations", op)
        nar = api.store.get(db, "narrations", op["narration_id"])
        nar["state"] = "running"
        api.store.put(db, "narrations", nar)

    panel_source = nar.get("source") == "storyboard_panels"
    position_key = "position" if panel_source else "slide"
    unit = "panels" if panel_source else "slides"

    def check():
        current = api.get_operation(operation_id)
        require(current["state"] != "cancelled", "Narration was cancelled.", "cancelled")
        require(now() < op["deadline"], "Narration time allowance exhausted.", "execution_timeout")

    async def one(text, indices):
        check()
        key = fingerprint(text, nar["settings"])
        with api.store.transaction() as db:
            current = api.store.get(db, "operations", operation_id)
            require(
                current["state"] == "running" and now() < op["deadline"],
                "Narration cancelled or expired.",
                "cancelled",
            )
            cached = audio_record(db, key)
            if not cached:
                require(
                    api.model_env,
                    "Enable model_env for explicitly authorized speech API access.",
                    "model_access_required",
                )
                require(
                    credential(nar["settings"]["provider"]),
                    "Speech API key is unavailable.",
                    "speech_unavailable",
                )
                prior = db.execute("SELECT data FROM speech_attempts WHERE id=?", (key,)).fetchone()
                if prior:
                    attempt = json.loads(prior[0])
                    other = api.store.get(db, "operations", attempt["operation_id"])
                    require(
                        not (other["state"] == "running" and now() < other["deadline"]),
                        "Identical speech is already in flight.",
                        "speech_busy",
                    )
                    require(
                        op["retry_uncertain"],
                        "A previous speech request has uncertain completion; acknowledge retry_uncertain with a new request before spending again.",
                        "speech_completion_uncertain",
                    )
                require(
                    op["requests_used"] < op["grant"]["max_requests"]
                    and op["characters_used"] + len(text) <= op["grant"]["max_characters"],
                    "Narration work allowance exhausted.",
                    "execution_limit",
                )
                op["requests_used"] += 1
                op["characters_used"] += len(text)
                current.update(requests_used=op["requests_used"], characters_used=op["characters_used"])
                api.store.put(db, "operations", current)
                api.store.put(
                    db,
                    "speech_attempts",
                    {"id": key, "operation_id": operation_id, "state": "completion_uncertain"},
                )
        if not cached:
            task = asyncio.create_task(synthesize(text, nar["settings"], op["deadline"] - now()))
            try:
                while not task.done():
                    check()
                    await asyncio.wait({task}, timeout=0.1)
                data = task.result()
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            check()
            with wave.open(io.BytesIO(data), "rb") as w:
                require(
                    w.getframerate() == 24000
                    and w.getnchannels() == 1
                    and w.getsampwidth() == 2
                    and w.getnframes() > 0
                    and len(data) <= 64 * 1024 * 1024 + 44
                    and len(w.readframes(w.getnframes())) == w.getnframes() * 2,
                    "Speech WAV format is invalid.",
                    "invalid_audio",
                )
                meta = {
                    "id": key,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "samples": w.getnframes(),
                    "sample_rate": 24000,
                    "duration_seconds": w.getnframes() / 24000,
                    "settings": nar["settings"],
                    "text": text,
                    "mime_type": "audio/wav",
                    "ai_generated": True,
                }
            with api.store.transaction() as db:
                current = api.store.get(db, "operations", operation_id)
                require(
                    current["state"] == "running" and now() < op["deadline"],
                    "Narration cannot commit after cancellation or timeout.",
                    "cancelled",
                )
                db.execute("INSERT INTO speech_audio VALUES (?,?,?)", (key, json.dumps(meta), data))
                db.execute("DELETE FROM speech_attempts WHERE id=?", (key,))
            cached = meta, data
        with api.store.transaction() as db:
            current = api.store.get(db, "operations", operation_id)
            require(current["state"] == "running", "Narration cancelled.", "cancelled")
            nar["clips"].extend(
                {
                    position_key: i + 1,
                    **({"panel_id": nar["panel_ids"][i]} if panel_source else {}),
                    "audio_id": key,
                    "sha256": cached[0]["sha256"],
                    "samples": cached[0]["samples"],
                    "duration_seconds": cached[0]["duration_seconds"],
                }
                for i in indices
            )
            nar["clips"].sort(key=lambda c: c[position_key])
            api.store.put(db, "narrations", nar)
            current["progress"] = {f"completed_{unit}": len(nar["clips"]), f"total_{unit}": len(nar["notes"])}
            api.store.put(db, "operations", current)

    async def work():
        # One task per distinct speech input; repeated slides share a single request.
        groups = {}
        for i, text in enumerate(nar["notes"]):
            key = fingerprint(text, nar["settings"])
            groups.setdefault(key, (text, []))[1].append(i)
        semaphore = asyncio.Semaphore(op.get("concurrency", 3))

        async def limited(text, indices):
            async with semaphore:
                try:
                    return await one(text, indices)
                except Exception as exc:
                    # Keep diagnostic categories, never provider response text or credentials.
                    failure = (
                        {
                            "panel_ids": [nar["panel_ids"][i] for i in indices],
                            "positions": [i + 1 for i in indices],
                        }
                        if panel_source
                        else {"slides": [i + 1 for i in indices]}
                    )
                    failure["type"] = type(exc).__name__
                    status = getattr(exc, "status_code", getattr(exc, "code", None))
                    if type(status) is int and 100 <= status <= 599:
                        failure["http_status"] = status
                    if isinstance(exc, StoriesError):
                        failure["code"] = exc.code
                    with api.store.transaction() as db:
                        current = api.store.get(db, "operations", operation_id)
                        current.setdefault("panel_errors" if panel_source else "slide_errors", []).append(
                            failure
                        )
                        api.store.put(db, "operations", current)
                        if status == 429:
                            # A rate/quota rejection is known not to have produced audio.
                            db.execute(
                                "DELETE FROM speech_attempts WHERE id=? AND json_extract(data, '$.operation_id')=?",
                                (fingerprint(text, nar["settings"]), operation_id),
                            )
                    if status == 429:
                        raise StoriesError(
                            "speech_rate_limited",
                            "Speech provider rejected the request due to a rate or quota limit.",
                            "Wait for the provider limit to reset or increase its quota, then submit a new request. Completed audio will be reused.",
                        ) from None
                    raise

        tasks = [asyncio.create_task(limited(text, indices)) for text, indices in groups.values()]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Other slides finish and remain retained even when one request fails.
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    try:
        asyncio.run(work())
        check()
        state, error = "succeeded", None
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            state, error = (
                "interrupted",
                {
                    "code": "speech_completion_uncertain",
                    "message": "Interrupted; in-flight synthesis may have been billed. Completed audio remains retained.",
                },
            )
        elif isinstance(exc, StoriesError):
            state, error = "failed", exc.public()["error"]
        else:
            state, error = (
                "failed",
                {
                    "code": "speech_completion_uncertain",
                    "message": "Speech request or response processing failed; completion may be uncertain.",
                    "remedy": "Check provider access and inspect completed audio. A new request with retry_uncertain=true explicitly permits another billable attempt.",
                },
            )
    with api.store.transaction() as db:
        current = api.store.get(db, "operations", operation_id)
        if current["state"] == "cancelled":
            state = "cancelled"
        elif state == "succeeded" and now() >= op["deadline"]:
            state, error = (
                "failed",
                {"code": "execution_timeout", "message": "Narration time allowance exhausted."},
            )
        current.update(state=state, error=error, cleanup="complete", finished_at=now())
        nar["state"] = state
        if state == "succeeded":
            current["result"] = {"narration_id": nar["id"], "revision_id": nar["revision_id"]}
        api.store.put(db, "operations", current)
        api.store.put(db, "narrations", nar)
        api.store.event(
            db, op["story_id"], "narration_" + state, operation_id=operation_id, narration_id=nar["id"]
        )
    return current
