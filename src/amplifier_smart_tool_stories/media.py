"""Retained media, validated without network access or implicit transformation."""

import base64
import hashlib
import io
import json
import subprocess
import tempfile
import warnings
from pathlib import Path

from .errors import StoriesError, require

MAX_ASSET_BYTES = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_RENDER_IMAGE_BYTES = 64 * 1024 * 1024
EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "text/vtt": "vtt",
}


def inspect_media(data, mime_type):
    require(
        isinstance(data, bytes) and 0 < len(data) <= MAX_ASSET_BYTES,
        "Supply nonempty media up to 256 MiB per asset; choose a smaller file if needed.",
    )
    require(mime_type in EXTENSIONS, "Supported media: PNG, JPEG, WebP, GIF, MP4, WebM and WebVTT.")
    details = {}
    if mime_type.startswith("image/"):
        from PIL import Image

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as im:
                    require(Image.MIME[im.format] == mime_type, "Image content does not match MIME type.")
                    require(
                        im.width * im.height <= MAX_IMAGE_PIXELS,
                        "Image exceeds 40 million decoded pixels; explicitly resize before importing.",
                    )
                    details = {"width": im.width, "height": im.height, "frames": getattr(im, "n_frames", 1)}
                    im.verify()
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise StoriesError(
                "invalid_media", "Image cannot be decoded safely; supply a valid image."
            ) from exc
    elif mime_type.startswith("video/"):
        require(
            (mime_type == "video/mp4" and data[4:8] == b"ftyp")
            or (mime_type == "video/webm" and data[:4] == b"\x1aE\xdf\xa3"),
            "Video container does not match MIME type.",
        )
        with tempfile.NamedTemporaryFile(suffix="." + EXTENSIONS[mime_type]) as f:
            f.write(data)
            f.flush()
            try:
                result = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-protocol_whitelist",
                        "file",
                        "-show_entries",
                        "format=duration:stream=codec_type,codec_name,width,height",
                        "-of",
                        "json",
                        f.name,
                    ],
                    capture_output=True,
                    timeout=30,
                )
            except FileNotFoundError as exc:
                raise StoriesError(
                    "missing_dependency",
                    "Video inspection requires ffprobe.",
                    "Install ffmpeg (which includes ffprobe), then retry.",
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise StoriesError("invalid_media", "Video inspection exceeded 30 seconds.") from exc
        require(result.returncode == 0, "Video could not be inspected; supply a valid MP4 or WebM.")
        info = json.loads(result.stdout)
        streams = info.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        require(video is not None, "Video has no video stream.")
        details = {
            "width": video.get("width"),
            "height": video.get("height"),
            "codec": video.get("codec_name"),
            "duration_seconds": float(info.get("format", {}).get("duration", 0)),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        }
    else:
        try:
            require(data.decode("utf-8-sig").startswith("WEBVTT"), "Caption track must begin with WEBVTT.")
        except UnicodeError as exc:
            raise StoriesError("invalid_media", "Caption tracks must be UTF-8 WebVTT.") from exc
    return details


def prepare(name, mime_type, attribution, path=None, data_base64=None):
    require(isinstance(name, str) and 0 < len(name) <= 300, "Supply a short asset name.")
    require(isinstance(attribution, str), "Attribution must be text.")
    require((path is None) != (data_base64 is None), "Supply exactly one of path or data_base64.")
    if path is not None:
        with Path(path).expanduser().open("rb") as f:
            data = f.read(MAX_ASSET_BYTES + 1)
    else:
        require(
            isinstance(data_base64, str) and len(data_base64) <= (MAX_ASSET_BYTES + 2) // 3 * 4,
            "Encoded media exceeds the 256 MiB asset budget.",
        )
        try:
            data = base64.b64decode(data_base64, validate=True)
        except ValueError as exc:
            raise StoriesError("invalid_media", "Media must be valid base64.") from exc
    info = inspect_media(data, mime_type)
    sha = hashlib.sha256(data).hexdigest()
    metadata = {
        "name": name,
        "mime_type": mime_type,
        "attribution": attribution,
        "sha256": sha,
        "size_bytes": len(data),
        **info,
    }
    asset_id = "asset_" + hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    return {"id": asset_id, **metadata}, data


def retain(db, metadata, data):
    db.execute("INSERT OR IGNORE INTO media VALUES (?,?,?)", (metadata["id"], json.dumps(metadata), data))
    return metadata


def load(db, asset_id):
    require(isinstance(asset_id, str), "Asset identity must be text.")
    row = db.execute("SELECT metadata,content FROM media WHERE id=?", (asset_id,)).fetchone()
    require(row is not None, "Asset is unavailable; import it into this store first.", "missing_asset")
    meta, data = json.loads(row[0]), row[1]
    require(
        hashlib.sha256(data).hexdigest() == meta["sha256"],
        "Retained media failed integrity check.",
        "invalid_media",
    )
    return meta, data


def select(db, asset_ids):
    require(
        isinstance(asset_ids, list) and len(asset_ids) <= 100 and all(isinstance(i, str) for i in asset_ids),
        "Supply at most 100 asset identities.",
    )
    require(len(set(asset_ids)) == len(asset_ids), "Asset identities must be unique.")
    return [load(db, i)[0] for i in asset_ids]


def warnings_for(assets):
    return [
        {
            "asset_id": a["id"],
            "message": "Large image: keep original, explicitly resize a copy, or export ZIP with separate assets.",
            "size_bytes": a["size_bytes"],
            "width": a["width"],
            "height": a["height"],
        }
        for a in assets
        if a["mime_type"].startswith("image/")
        and (a["size_bytes"] > 2 * 1024 * 1024 or a["width"] > 2560 or a["height"] > 1440)
    ]


def bindings(html, assets, strict=False):
    """Validate element media references; CSS and arbitrary URLs never become asset authority."""
    from .artifacts import parse_html

    soup = parse_html(html)
    index = {"asset:" + a["id"]: a for a in assets}
    used, missing = set(), []
    for node in soup.select("img,video,audio,source,track"):
        for attr in ("src", "poster"):
            value = node.get(attr)
            if not value:
                continue
            asset = index.get(value)
            if asset:
                expected = (
                    "image/"
                    if node.name == "img" or attr == "poster"
                    else "text/vtt"
                    if node.name == "track"
                    else "video/"
                )
                require(
                    asset["mime_type"].startswith(expected),
                    "Media reference type does not match its element.",
                )
                used.add(asset["id"])
            else:
                missing.append(value)
    if strict:
        require(
            not missing,
            "Media references must use retained asset:ASSET_ID values; import and bind all media before export.",
            "missing_asset",
        )
    return used, missing


def image_payload(db, assets):
    images = [a for a in assets if a["mime_type"].startswith("image/")]
    require(
        sum(a["size_bytes"] for a in images) <= MAX_RENDER_IMAGE_BYTES,
        "Static review exceeds its 64 MiB encoded-image budget; explicitly resize copies or review fewer images.",
    )
    result = {
        "asset:" + a["id"]: {
            "mime_type": a["mime_type"],
            "data": base64.b64encode(load(db, a["id"])[1]).decode(),
        }
        for a in images
    }
    for a in assets:
        result.setdefault("asset:" + a["id"], {"mime_type": a["mime_type"]})
    return result


class MediaLibrary:
    def import_media(self, name, mime_type, request_id, path=None, data_base64=None, attribution=""):
        """Retain explicitly supplied media unchanged; return its identity and size warnings, without model use."""
        meta, data = prepare(name, mime_type, attribution, path, data_base64)

        def action(db):
            retain(db, meta, data)
            return {"status": "succeeded", "asset": meta, "warnings": warnings_for([meta])}

        return self._mutation(request_id, "import_media", meta, action)

    def resize_media(self, asset_id, max_width, max_height, request_id):
        """Explicitly create a resized PNG copy of a still image; preserve the original and aspect ratio."""
        require(
            type(max_width) is int
            and type(max_height) is int
            and 0 < max_width <= 10000
            and 0 < max_height <= 10000,
            "Dimensions must be integers from 1 to 10000.",
        )

        def action(db):
            from PIL import Image

            original, data = load(db, asset_id)
            require(
                original["mime_type"].startswith("image/") and original.get("frames", 1) == 1,
                "Resize supports still images only; animated originals remain unchanged.",
            )
            with Image.open(io.BytesIO(data)) as im:
                from PIL import ImageOps

                im = ImageOps.exif_transpose(im).convert("RGBA")
                im.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                im.save(output, format="PNG")
            metadata, resized = prepare(
                original["name"] + " (resized)",
                "image/png",
                original["attribution"],
                data_base64=base64.b64encode(output.getvalue()).decode(),
            )
            metadata["derived_from"] = asset_id
            metadata["transformation"] = {"kind": "resize", "max_width": max_width, "max_height": max_height}
            # Include derivative provenance in identity, even when pixels match another asset.
            metadata["id"] = (
                "asset_" + hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
            )
            retain(db, metadata, resized)
            return {"status": "succeeded", "asset": metadata, "warnings": warnings_for([metadata])}

        return self._mutation(request_id, "resize_media", [asset_id, max_width, max_height], action)

    def get_media(self, story_id, revision_id, asset_id):
        """Read media attached to this exact revision as base64; no source-path access or model call."""
        rev = self.get_revision(story_id, revision_id)
        require(
            asset_id in {a["id"] for a in rev.get("assets", [])},
            "Asset is not attached to this revision.",
            "missing_asset",
        )
        with self.store.transaction() as db:
            meta, data = load(db, asset_id)
        return {"asset": meta, "data_base64": base64.b64encode(data).decode()}

    def revise_media(self, story_id, revision_id, asset_ids, request_id, html=None):
        """Create an unreviewed revision with explicit media bindings and optional replacement HTML; preserve the base."""

        def action(db):
            story = self.store.get(db, "stories", story_id)
            base = self._revision(story, revision_id)
            require(
                base.get("kind") == "presentation",
                "Use revise-storyboard for storyboard assets; revise-media supports presentations.",
            )
            assets = select(db, asset_ids)
            markup = base["html"] if html is None else html
            bindings(markup, assets, strict=True)
            rev = self._new_revision(
                story,
                markup,
                base=revision_id,
                evidence=base["evidence"],
                assets=assets,
                limitations=["Media revision requires fresh review."],
            )
            rev["changes"] = {
                "summary": "Explicit media/HTML revision; review and acceptance are not inherited.",
                "material_changes": ["Updated the selected media assets and/or HTML."],
                "omissions": [],
                "assumptions": [],
            }
            self.store.put(db, "stories", story)
            self.store.event(db, story_id, "revision_created", revision_id=rev["id"])
            return {
                "status": "succeeded",
                "story_id": story_id,
                "revision_id": rev["id"],
                "warnings": warnings_for(assets),
            }

        return self._mutation(request_id, "revise_media", [story_id, revision_id, asset_ids, html], action)


def portable_markup(html):
    """Validate bounded static markup, not arbitrary HTML/SVG browser safety."""
    from urllib.parse import urlsplit

    import tinycss2

    from .artifacts import parse_html

    soup = parse_html(html)
    require(
        not soup.select("script,iframe,frame,frameset,object,embed,applet,link,base,meta[http-equiv],form"),
        "Portable media export requires static HTML without scripts, frames, external stylesheets or base URLs.",
        "external_dependency",
    )
    # A deliberately bounded inline SVG subset: geometry, text and local icons/
    # paint servers. No animation, foreign HTML, remote images or filter loaders.
    svg_elements = {
        "svg",
        "g",
        "defs",
        "symbol",
        "use",
        "image",
        "a",
        "title",
        "desc",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "text",
        "tspan",
        "textpath",
        "lineargradient",
        "radialgradient",
        "stop",
        "clippath",
        "mask",
        "pattern",
        "marker",
    }
    local_ids = {node["id"] for node in soup.find_all(id=True)}

    def local_reference(value):
        return value.startswith("#") and value[1:] in local_ids

    def navigation(value):
        # Browser URL parsing removes tabs/newlines; reject controls instead of
        # trying to recognize every obfuscated executable scheme.
        value = value.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            return False
        if value.startswith("#"):
            return True
        try:
            url = urlsplit(value)
            return url.scheme.lower() in {"http", "https"} and bool(url.netloc)
        except ValueError:
            return False

    svg_paint = []
    for node in soup.find_all(True):
        in_svg = node.name == "svg" or node.find_parent("svg") is not None
        if in_svg:
            require(
                node.name.lower() in svg_elements,
                "Portable media export supports only static inline SVG geometry, text and local icons; "
                "animation, foreign content and other SVG elements are unsupported.",
                "external_dependency",
            )
        require(
            not any(key.startswith("on") for key in node.attrs),
            "Portable media export cannot include active event handlers.",
            "external_dependency",
        )
        for key, value in node.attrs.items():
            key = key.lower()
            require(
                key not in {"srcdoc", "ping", "action", "formaction", "data", "codebase", "archive"}
                and key not in {"xml:base", "manifest", "lowsrc", "dynsrc"},
                "Portable media export cannot include active content or unretained resource attributes.",
                "external_dependency",
            )
            if key in {"href", "xlink:href"}:
                allowed = (
                    navigation(value) if node.name in {"a", "area"} else in_svg and local_reference(value)
                )
                require(
                    allowed,
                    "Portable media export permits HTTP(S) or fragment navigation links and "
                    "local inline SVG references only; external SVG resources are not packaged.",
                    "external_dependency",
                )
            if key in {"src", "poster"}:
                require(
                    node.name in {"img", "video", "audio", "source", "track"},
                    "Portable media export requires registered img/video media resources.",
                    "external_dependency",
                )
            if in_svg and key in {
                "fill",
                "stroke",
                "filter",
                "clip-path",
                "mask",
                "marker",
                "marker-start",
                "marker-mid",
                "marker-end",
                "cursor",
                "color-profile",
            }:
                svg_paint.append(value)
        require(
            not node.get("srcset") and not node.get("background"),
            "Use registered img/video assets instead of srcset or background attributes.",
            "external_dependency",
        )
    css = (
        "\n".join(n.get_text() for n in soup.select("style"))
        + "\n"
        + "\n".join(n.get("style", "") for n in soup.find_all(True))
    )

    def resource_tokens(tokens, allow_local=False):
        for token in tokens:
            if token.type == "error":
                return True
            if token.type == "url" and not (allow_local and local_reference(token.value)):
                return True
            if token.type == "at-keyword" and token.lower_value == "import":
                return True
            if token.type == "function":
                # image-set/image can load string URLs without a url() token.
                if token.lower_name in {"image-set", "-webkit-image-set", "image"}:
                    return True
                if token.lower_name == "url":
                    args = [a for a in token.arguments if a.type not in {"whitespace", "comment"}]
                    if not (
                        allow_local
                        and len(args) == 1
                        and args[0].type == "string"
                        and local_reference(args[0].value)
                    ):
                        return True
                elif resource_tokens(token.arguments, allow_local):
                    return True
            if getattr(token, "content", None) and resource_tokens(token.content, allow_local):
                return True
        return False

    require(
        not resource_tokens(tinycss2.parse_component_value_list(css)),
        "Portable media export cannot include CSS resource URLs; use registered image elements.",
        "external_dependency",
    )
    require(
        not any(resource_tokens(tinycss2.parse_component_value_list(v), True) for v in svg_paint),
        "Portable media export permits only local fragment URLs in SVG paint attributes.",
        "external_dependency",
    )
