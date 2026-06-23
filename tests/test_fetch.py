"""Tests for loominum.fetch -- HTML to md/text + link extraction."""
import pytest

bs4 = pytest.importorskip("bs4")
from loominum.fetch import html_to_md, html_to_text, list_links, _is_gdoc


def test_html_to_md_headings_and_paragraphs():
    html = "<h1>Title</h1><p>Hello <strong>world</strong>.</p>"
    md = html_to_md(html)
    assert "# Title" in md
    assert "Hello **world**." in md


def test_html_to_md_table():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    md = html_to_md(html)
    assert "| A | B |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md


def test_html_to_md_link():
    html = '<p>See <a href="https://example.com/x">here</a></p>'
    md = html_to_md(html)
    assert "[here](https://example.com/x)" in md


def test_html_to_md_nested_lists():
    html = "<ul><li>top<ul><li>sub</li></ul></li><li>top2</li></ul>"
    md = html_to_md(html)
    assert "- top" in md
    assert "  - sub" in md
    assert "- top2" in md


def test_html_to_md_code_block():
    html = '<pre><code class="language-python">x = 1</code></pre>'
    md = html_to_md(html)
    assert "```python" in md
    assert "x = 1" in md


def test_html_to_md_drops_scripts_and_styles():
    html = "<p>visible</p><script>bad()</script><style>.x{}</style>"
    md = html_to_md(html)
    assert "visible" in md
    assert "bad" not in md
    assert ".x{}" not in md


def test_html_to_text_basic():
    html = "<h1>Title</h1><p>Body text.</p><script>nope</script>"
    text = html_to_text(html)
    assert "Title" in text
    assert "Body text." in text
    assert "nope" not in text


def test_list_links_basic():
    html = '<a href="/a">A</a><a href="https://example.com/b">B</a>'
    links = list_links(html, base_url="https://site.com")
    assert ("https://site.com/a", "A") in links
    assert ("https://example.com/b", "B") in links


def test_list_links_regex_filter():
    html = '<a href="/posts/1">P1</a><a href="/about">About</a>'
    links = list_links(html, base_url="https://s.com", pattern=r"posts/")
    assert len(links) == 1
    assert links[0][0] == "https://s.com/posts/1"


def test_list_links_dedup():
    html = '<a href="/x">first</a><a href="/x">second</a>'
    links = list_links(html, base_url="https://s.com")
    assert len(links) == 1


def test_gdoc_detection():
    assert _is_gdoc('<div class="doc-content">stuff</div>')
    assert _is_gdoc('<meta name="google-sheets-html-origin">other')
    assert not _is_gdoc("<html><body>regular</body></html>")


def test_html_to_md_extracts_article_over_body():
    html = "<body><nav>nav</nav><article><h1>real</h1></article><footer>foot</footer></body>"
    md = html_to_md(html)
    assert "# real" in md
    # nav and footer are dropped at the render layer
    assert "nav" not in md.lower() or "navigation" not in md.lower()
