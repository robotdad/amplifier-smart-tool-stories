"""Isolated, bounded static renderer. No scripts or external/local resource fetching."""

import base64
import hashlib
import io
import json
import re
import sys
from collections import Counter
from contextlib import redirect_stdout

from .artifacts import parse_html, preview
from .errors import StoriesError

MAX_STORYBOARD_RENDER_BYTES = 64 * 1024 * 1024
MAX_RENDER_INPUT_BYTES = 300_000_000


def check_storyboard_render_bytes(size):
    if size > MAX_STORYBOARD_RENDER_BYTES:
        raise StoriesError(
            "render_resource_limit",
            "Storyboard review exceeds the 64 MiB combined PDF/JPEG output budget.",
            "Use retained structured HTML/ZIP review, or explicitly reduce media bytes. "
            "No panels were truncated or merged; this is not a panel-count limit.",
        )


def expected_visible_text(html, stylesheets):
    """Exclude nonvisual metadata, not arbitrary content hidden by faulty CSS.

    Notes have explicit authoring semantics (.notes / data-speaker-notes). Only
    their non-painted text is optional. Use the renderer's CSS cascade, including
    media queries and inherited visibility, rather than guessing from inline CSS
    or dropping every element that failed to produce a layout box.
    """
    from weasyprint.css import get_all_computed_styles

    style_for = get_all_computed_styles(html, user_stylesheets=stylesheets)
    texts = []

    def visit(element, notes=False, suppressed=False):
        classes = set(element.get("class", "").split())
        if element.tag in {"style", "script", "template", "nav"} or classes.intersection(
            {"navigation", "slide-counter", "nav-dots"}
        ):
            return
        style = style_for(element)
        notes = notes or "notes" in classes or "data-speaker-notes" in element.attrib
        suppressed = suppressed or style["display"] == ("none",) or style["opacity"] == 0
        include = not notes or (not suppressed and style["visibility"] == "visible")
        if include and element.text:
            texts.append(element.text)
        for child in element:
            if isinstance(child.tag, str):
                visit(child, notes, suppressed)
            if include and child.tail:
                texts.append(child.tail)

    body = html.etree_element.find("body")
    root_style = style_for(html.etree_element)
    visit(body, suppressed=root_style["display"] == ("none",) or root_style["opacity"] == 0)
    return " ".join(text.strip() for text in texts if text.strip())


def visible_text_boxes(box, transparent=False, clip=None, transformed=False):
    """Yield text with its rectangular ancestor-overflow coverage finding.

    Layout boxes survive overflow clipping. Intersect ancestor padding boxes
    before counting text as rendered; partial text is not full word coverage.
    This is a bounds check, not glyph/occlusion analysis. Transformed clipping
    cannot be inferred from these untransformed coordinates.
    """
    transparent = transparent or box.style["opacity"] == 0
    if transparent:
        return
    transformed = transformed or bool(box.style["transform"])
    if getattr(box, "text", "").strip() and box.style["visibility"] == "visible":
        finding = None
        if clip is not None:
            left, top, right, bottom = clip
            x, y = box.position_x, box.position_y
            end_x, end_y = x + box.width, y + box.height
            if transformed:
                finding = "overflow clipping unverified for transformed text"
            elif right <= left or bottom <= top or end_x <= left or x >= right or end_y <= top or y >= bottom:
                finding = "text fully clipped by ancestor overflow"
            elif x < left - 1 or y < top - 1 or end_x > right + 1 or end_y > bottom + 1:
                finding = "text partially clipped by ancestor overflow"
        yield box, finding
    # WeasyPrint clips content/children to the padding box, not the border or
    # content box. Page clipping remains the separate canvas-bounds check.
    if box.style["overflow"] != "visible" and box.element_tag is not None:
        x, y = box.padding_box_x(), box.padding_box_y()
        bounds = (x, y, x + box.padding_width(), y + box.padding_height())
        clip = (
            bounds
            if clip is None
            else (
                max(clip[0], bounds[0]),
                max(clip[1], bounds[1]),
                min(clip[2], bounds[2]),
                min(clip[3], bounds[3]),
            )
        )
    # Include positioned placeholders, as descendants(placeholders=True) did.
    for child in box.children:
        yield from visible_text_boxes(child, transparent, clip, transformed)


def render(html, include_pdf=False, media=None):
    import pypdfium2 as pdfium
    from weasyprint import CSS, HTML
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    media = media or {}
    clean, _ = preview(html, [{"id": key[6:]} for key in media])
    soup = parse_html(clean)
    # Preview strips navigation; PDF delivery keeps validated link annotations.
    for link in soup.select("a[data-stories-link]"):
        link["href"] = link["data-stories-link"]
    for video in soup.select("video"):
        if video.get("poster") in media:
            poster = soup.new_tag("img", src=video["poster"])
            for key in ("style", "width", "height", "class"):
                if video.get(key):
                    poster[key] = video[key]
            poster["alt"] = "Video poster (playback not inspected)"
            video.replace_with(poster)
        else:
            video.clear()
            video.string = "[Video: playback and audio not inspected]"
    clean = str(soup)
    slides = soup.select(".slide")
    document = bool(soup.select_one("article.stories-document"))
    storyboard = bool(soup.select_one("article.stories-storyboard"))
    if len(slides) > 12:
        raise ValueError("Rendered review supports at most 12 slides.")
    denied = []

    class NoFetch(URLFetcher):
        def fetch(self, url, headers=None):
            if url in media and media[url]["mime_type"].startswith("image/"):
                return URLFetcherResponse(
                    url, base64.b64decode(media[url]["data"]), {"Content-Type": media[url]["mime_type"]}
                )
            denied.append(str(url).split(":", 1)[0])
            raise ValueError("Resource fetching disabled")

    css = CSS(
        string="""
        @page { size: 1280px 720px; margin: 0; }
        html, body { margin:0!important; padding:0!important; width:1280px!important; }
        .slide { box-sizing:border-box!important;
          width:1280px!important; height:720px!important; min-height:720px!important;
          position:relative!important; opacity:1!important; visibility:visible!important;
          transform:none!important; break-before:page; break-inside:avoid; }
        .slide:first-child { break-before:auto; }
        nav,.navigation,.slide-counter,.nav-dots { display:none!important; }
    """
    )
    source = HTML(
        string=clean, url_fetcher=NoFetch(allowed_protocols=()), media_type="print" if document else "screen"
    )
    stylesheets = [] if document else [css]
    expected = expected_visible_text(source, stylesheets)
    doc = source.render(stylesheets=stylesheets)
    # Storyboard length follows content, not a page/panel quota. Preserve the
    # unrelated document/deck budget; storyboard work is byte/time bounded.
    if not storyboard and len(doc.pages) > 12:
        raise ValueError("Rendered review exceeds 12 pages; shorten the story.")
    findings, rendered = [], []
    for i, page in enumerate(doc.pages):
        for box, clipping in visible_text_boxes(page._page_box):
            text = box.text
            if clipping:
                findings.append(f"Page {i + 1}: {clipping}: {text[:80]}")
            else:
                rendered.append(text)
            if (
                box.position_x < -1
                or box.position_y < -1
                or box.position_x + box.width > page.width + 1
                or box.position_y + box.height > page.height + 1
            ):
                findings.append(f"Page {i + 1}: text outside the canvas: {text[:80]}")
            if box.style["font_size"] < (12 if document else 16):
                findings.append(f"Page {i + 1}: text below minimum readable size: {text[:80]}")
    if slides and len(doc.pages) != len(slides):
        findings.append(
            f"{len(slides)} slides rendered as {len(doc.pages)} pages; layout spilled or collapsed."
        )
    if denied:
        findings.append("Styles requested blocked external resources; rendering is incomplete.")

    def words(value):
        return Counter(re.findall(r"\w+", value.replace("\u00ad", "").casefold()))

    missing = words(expected) - words(" ".join(rendered))
    if missing:
        findings.append("Text missing from rendered layout: " + ", ".join(list(missing)[:15]))
    pdf_bytes = doc.write_pdf()
    render_bytes = len(pdf_bytes)
    if storyboard:
        check_storyboard_render_bytes(render_bytes)
    del doc
    pdf = pdfium.PdfDocument(pdf_bytes)
    images = []
    page_count = len(pdf)
    try:
        # Rasterize one page at a time at the existing scale, releasing each
        # bitmap immediately. Never keep an unbounded set of decoded pages.
        for page in pdf:
            try:
                bitmap = page.render(scale=1)
                try:
                    output = io.BytesIO()
                    with bitmap.to_pil().convert("RGB") as image:
                        image.save(output, format="JPEG", quality=40 if document else 45, optimize=True)
                    encoded = output.getvalue()
                finally:
                    bitmap.close()
                render_bytes += len(encoded)
                if storyboard:
                    check_storyboard_render_bytes(render_bytes)
                images.append(
                    {
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                        "data": base64.b64encode(encoded).decode(),
                        "media_type": "image/jpeg",
                    }
                )
            finally:
                page.close()
    finally:
        pdf.close()
    return {
        "images": images,
        **({"pdf": base64.b64encode(pdf_bytes).decode()} if include_pdf else {}),
        "renderer": "WeasyPrint Letter document / PDFium"
        if document
        else "WeasyPrint static 1280x720 / PDFium",
        "findings": list(dict.fromkeys(findings))[:30],
        "page_count": page_count,
        "rendered_text": " ".join(rendered),
        "expected_text": expected,
    }


if __name__ == "__main__":
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (35, 35))
        # JSON escaping and attached image bytes have a separate IPC budget.
        raw = sys.stdin.buffer.read(MAX_RENDER_INPUT_BYTES + 1)
        if len(raw) > MAX_RENDER_INPUT_BYTES:
            raise StoriesError(
                "render_resource_limit",
                "Static render input exceeds the 300 MB JSON payload budget.",
                "Use structured HTML/ZIP review or explicitly reduce attached media bytes; "
                "do not truncate or merge panels to satisfy a count quota.",
            )
        value = json.loads(raw)
        with redirect_stdout(io.StringIO()):
            result = render(value["html"], value.get("include_pdf", False), value.get("media"))
        print(json.dumps(result))
    except StoriesError as exc:
        print(json.dumps(exc.public()))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"error": f"Static rendering failed ({type(exc).__name__}): {str(exc)[:300]}"}))
        sys.exit(1)
