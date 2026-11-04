"""Real, provider-free static renders: notes are not missing slide content."""

import asyncio
import re
from collections import Counter

import pytest

from amplifier_smart_tool_stories.quality import record, render


def artifact(content, css="", document=False):
    wrapper = 'article class="stories-document"' if document else 'section class="slide"'
    tag = wrapper.split()[0]
    return (
        "<html><head><style>"
        "@page {size:1280px 720px;margin:0}"
        "body{margin:0;font-family:sans-serif;font-size:24px}"
        ".slide{padding:40px}h1{font-size:48px}"
        + css
        + f"</style></head><body><{wrapper}>{content}</{tag}></body></html>"
    )


def inspect(html):
    # Exercise the bounded subprocess interface, not a mocked renderer.
    return asyncio.run(render(html, 30))


def words(text):
    return Counter(re.findall(r"\w+", text.casefold()))


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize("marker", ['class="notes"', "data-speaker-notes"])
def test_good_cover_with_hidden_repeated_notes(document, marker):
    cover = "<h1>Useful work. Without having to ask.</h1><p>Useful answers.</p>"
    note = f"<aside {marker}>Useful work. Useful answers. Presenter context only.</aside>"
    result = inspect(artifact(cover + note, ".notes,[data-speaker-notes]{display:none}", document))
    without_notes = inspect(artifact(cover, ".notes,[data-speaker-notes]{display:none}", document))
    assert result["findings"] == []
    assert "Useful work. Without having to ask." in result["rendered_text"]
    assert "Presenter" not in result["expected_text"]
    assert words(result["expected_text"]) == words(result["rendered_text"])
    # Removing notes changes neither the actual pages nor visible expectations.
    assert result["expected_text"] == without_notes["expected_text"]
    assert result["images"] == without_notes["images"]


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize("hidden", ["display:none", "visibility:hidden", "opacity:0"])
def test_hidden_ordinary_content_is_still_required(document, hidden):
    result = inspect(
        artifact(f'<h1>Repeated result</h1><p style="{hidden}">Repeated result</p>', document=document)
    )
    assert words(result["expected_text"])["repeated"] == 2
    assert words(result["rendered_text"])["repeated"] == 1
    assert any("Text missing from rendered layout: repeated, result" == issue for issue in result["findings"])
    # A model pass must not override this deterministic failure.
    review = record(
        "same revision",
        result,
        {"semantic": {"status": "passed", "findings": []}, "visual": {"status": "passed", "findings": []}},
        {},
    )
    assert not review["passed"]


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize("position", ["left:1400px", "top:900px"])
def test_page_clipped_visible_content_is_not_reclassified_as_notes(document, position):
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="position:absolute;' + position + '"><p>Required qualifier</p></div>'
            '<aside class="notes">Presenter only</aside>',
            ".notes{display:none}",
            document,
        )
    )
    assert "Required qualifier" in result["expected_text"]
    assert any("outside the canvas" in issue for issue in result["findings"])


def test_visible_notes_outside_page_remain_required():
    result = inspect(
        artifact(
            '<h1>Cover</h1><aside class="notes" style="position:absolute;left:1400px">Required note</aside>'
        )
    )
    assert "Required note" in result["expected_text"]
    assert any("outside the canvas: Required" in issue for issue in result["findings"])


def test_visible_notes_remain_required_and_tails_are_retained():
    result = inspect(
        artifact(
            '<h1>Cover</h1><p>Before <span class="notes" style="display:none">Secret</span> after</p>'
            '<aside class="notes">Visible note</aside>'
        )
    )
    assert result["findings"] == []
    assert "Secret" not in result["expected_text"]
    assert "Visible note" in result["expected_text"]
    assert "after" in result["expected_text"]


@pytest.mark.parametrize("document", [False, True])
def test_note_visibility_uses_the_cascade_and_render_media(document):
    result = inspect(
        artifact(
            '<h1>Cover</h1><aside class="notes">Screen note</aside>',
            ".notes{display:none!important}@media screen{.notes{display:block!important}}",
            document,
        )
    )
    assert result["findings"] == []
    assert ("Screen note" in result["expected_text"]) is not document


def test_visibility_override_inside_notes_and_inherited_transparency():
    result = inspect(
        artifact(
            '<h1>Cover</h1><aside class="notes" style="visibility:hidden">'
            'Invisible note <span style="visibility:visible">Visible explanation</span></aside>'
            '<div style="opacity:0"><aside data-speaker-notes>Transparent note</aside></div>'
        )
    )
    assert result["findings"] == []
    assert "Visible explanation" in result["expected_text"]
    assert "Invisible" not in result["expected_text"]
    assert "Transparent" not in result["expected_text"]


def test_nonvisual_metadata_navigation_and_comments_do_not_add_expected_text():
    result = inspect(
        artifact(
            '<h1 aria-hidden="true">Still visually present</h1>'
            "<!-- Comment is not content -->"
            "<nav>Next slide</nav><template>Template payload</template>"
            "<script>Script payload</script><style>.unused {color:red}</style>",
            "template{display:none}",
        )
    )
    assert result["findings"] == []
    assert result["expected_text"] == "Still visually present"


def test_repeated_visible_words_keep_their_multiplicity():
    result = inspect(artifact("<h1>Result result result</h1><p>Result result</p>"))
    assert result["findings"] == []
    assert words(result["expected_text"])["result"] == 5
    assert words(result["rendered_text"])["result"] == 5


def test_reviewer_zero_height_overflow_probe_has_identical_pixels_without_text():
    html = (
        '<html><body style="font-size:24px"><h1>Cover</h1>'
        '<div style="height:0;overflow:hidden"><p>Required qualifier</p></div></body></html>'
    )
    clipped = inspect(html)
    removed = inspect(html.replace("Required qualifier", ""))
    assert clipped["images"] == removed["images"]
    assert "Required qualifier" in clipped["expected_text"]
    assert clipped["rendered_text"] == "Cover"
    assert any("text fully clipped by ancestor overflow" in issue for issue in clipped["findings"])
    assert any(
        "Text missing from rendered layout: required, qualifier" in issue for issue in clipped["findings"]
    )
    assert removed["findings"] == []


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize(
    ("size", "finding"),
    [
        ("width:400px;height:80px", None),
        ("width:0;height:80px", "fully"),
        ("width:400px;height:0", "fully"),
        ("width:40px;height:80px", "partially"),
        ("width:400px;height:12px", "partially"),
    ],
)
def test_overflow_visible_fully_and_partially_clipped(document, size, finding):
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="overflow:hidden;'
            + size
            + '"><p style="margin:0;white-space:nowrap;line-height:32px">Required qualifier</p></div>',
            document=document,
        )
    )
    assert "Required qualifier" in result["expected_text"]
    if finding:
        assert "Required" not in result["rendered_text"]
        assert any(f"text {finding} clipped by ancestor overflow" in issue for issue in result["findings"])
        review = record(
            "clipped revision",
            result,
            {
                "semantic": {"status": "passed", "findings": []},
                "visual": {"status": "passed", "findings": []},
            },
            {},
        )
        assert not review["passed"]
    else:
        assert result["findings"] == []
        assert "Required qualifier" in result["rendered_text"]


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize("outer_height", [0, 12, 100])
def test_nested_overflow_intersects_all_ancestors_and_does_not_leak_to_siblings(document, outer_height):
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="overflow:hidden;height:'
            + str(outer_height)
            + 'px"><div style="overflow:hidden;height:80px">'
            '<p style="margin:0;line-height:32px">Nested qualifier</p></div></div>'
            '<p style="margin:0">Visible sibling</p>',
            document=document,
        )
    )
    assert "Visible sibling" in result["rendered_text"]
    if outer_height == 100:
        assert result["findings"] == []
        assert "Nested qualifier" in result["rendered_text"]
    else:
        assert "Nested" not in result["rendered_text"]
        assert any("clipped by ancestor overflow" in issue for issue in result["findings"])


@pytest.mark.parametrize("document", [False, True])
def test_overflow_clips_at_padding_not_content_or_border(document):
    # Text sits in padding below a zero-height content box; it is still painted.
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="height:0;padding-bottom:40px;border:6px solid;overflow:hidden">'
            '<p style="margin:0;line-height:32px">Padding qualifier</p></div>',
            document=document,
        )
    )
    assert result["findings"] == []
    assert "Padding qualifier" in result["rendered_text"]
    # A border is not extra space for the clipped content.
    clipped = inspect(
        artifact(
            '<h1>Cover</h1><div style="height:0;border:40px solid;overflow:hidden">'
            '<p style="margin:0">Border qualifier</p></div>',
            document=document,
        )
    )
    assert "Border qualifier" not in clipped["rendered_text"]
    assert any("fully clipped" in issue for issue in clipped["findings"])


@pytest.mark.parametrize("document", [False, True])
def test_overflow_does_not_make_clipped_visible_notes_optional(document):
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="height:0;overflow:hidden">'
            '<aside class="notes">Visible note qualifier</aside>'
            '<aside data-speaker-notes style="display:none">Hidden note detail</aside></div>',
            document=document,
        )
    )
    assert "Hidden note detail" not in result["expected_text"]
    assert "Visible note qualifier" in result["expected_text"]
    assert "Visible note qualifier" not in result["rendered_text"]
    assert any("fully clipped" in issue for issue in result["findings"])


def test_transformed_overflow_is_unverified_not_a_geometric_pass():
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="height:0;overflow:hidden">'
            '<p style="transform:translateY(-40px)">Transformed qualifier</p></div>'
        )
    )
    assert "Transformed qualifier" in result["expected_text"]
    assert "Transformed qualifier" not in result["rendered_text"]
    assert any("overflow clipping unverified for transformed text" in issue for issue in result["findings"])


@pytest.mark.parametrize("position", ["left:-30px", "top:-16px", "left:450px", "top:100px"])
def test_positioned_text_is_checked_against_offset_clip_rectangle(position):
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="position:relative;margin-left:100px;height:80px;'
            'width:400px;overflow:hidden"><p style="position:absolute;margin:0;white-space:nowrap;'
            + position
            + '">Positioned qualifier</p></div>'
        )
    )
    assert "Positioned qualifier" in result["expected_text"]
    assert "Positioned qualifier" not in result["rendered_text"]
    assert any("clipped by ancestor overflow" in issue for issue in result["findings"])


@pytest.mark.parametrize("overflow", ["visible", "hidden"])
def test_inner_clip_is_not_replaced_by_larger_outer_clip(overflow):
    result = inspect(
        artifact(
            '<h1>Cover</h1><div style="overflow:hidden;height:100px">'
            '<div style="height:0;overflow:' + overflow + '">'
            '<p style="margin:0">Inner qualifier</p></div></div>'
        )
    )
    if overflow == "visible":
        assert result["findings"] == []
        assert "Inner qualifier" in result["rendered_text"]
    else:
        assert "Inner qualifier" not in result["rendered_text"]
        assert any("fully clipped" in issue for issue in result["findings"])
