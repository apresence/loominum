"""HTML conversion and link extraction utilities for loominum drivers.

Vendored from /global/crew/scripts/fetch.py (CLI) -- this is the library form
intended for drivers that already have raw HTML (e.g. from CDP scraping) and
want to convert it to markdown/text or extract its links without re-fetching.

Optional install: ``pip install loominum[fetch]`` (pulls in beautifulsoup4).
If beautifulsoup4 is not installed, importing this module raises ImportError
with a helpful message.

Public API:
    html_to_md(html, gdoc=None) -> str
    html_to_text(html) -> str
    list_links(html, base_url=None, pattern=None) -> list[tuple[str, str]]
"""
from __future__ import annotations
import re
from urllib.parse import urljoin, unquote

try:
    from bs4 import BeautifulSoup, NavigableString
except ImportError as e:  # pragma: no cover -- install-time gate
    raise ImportError(
        "loominum.fetch requires beautifulsoup4. "
        "Install with: pip install 'loominum[fetch]'"
    ) from e


GDOC_SIGNATURES = (
    "docs-internal-guid",
    "google-sheets-html-origin",
    'id="doc-contents"',
    'class="doc-content"',
)


def _is_text(node) -> bool:
    return isinstance(node, NavigableString)


def _clean_text(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s


def _is_gdoc(html: str) -> bool:
    chunk = html[:4096]
    return any(sig in chunk for sig in GDOC_SIGNATURES)


def _unwrap_google_url(href: str) -> str:
    if href and href.startswith("https://www.google.com/url"):
        m = re.search(r"[?&]q=([^&]+)", href)
        if m:
            return unquote(m.group(1))
    return href


def _extract_content(soup):
    """Return the most specific content container: article > main > body."""
    for tag_name in ("article", "main"):
        tag = soup.find(tag_name)
        if tag:
            return tag
    return soup.body or soup


def _render_inline(node, gdoc: bool = False) -> str:
    if _is_text(node):
        return _clean_text(str(node))
    name = node.name
    if name is None:
        return ""
    inner = "".join(_render_inline(c, gdoc) for c in node.children)
    if name == "a":
        href = node.get("href", "")
        if gdoc:
            href = _unwrap_google_url(href)
        if href:
            return f"[{inner}]({href})"
        return inner
    if name in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else inner
    if name in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else inner
    if name == "code":
        return f"`{inner}`" if inner.strip() else inner
    if name == "br":
        return "  \n"
    if name == "span":
        style = node.get("style", "")
        if any(k in style for k in ("font-weight:700", "font-weight: 700", "font-weight:bold")):
            return f"**{inner.strip()}**" if inner.strip() else inner
        if "font-style:italic" in style:
            return f"*{inner.strip()}*" if inner.strip() else inner
        if "font-family" in style and any(
            f in style for f in ("Courier", "Mono", "Consolas")
        ):
            return f"`{inner}`" if inner.strip() else inner
        return inner
    if name == "img":
        alt = node.get("alt", "")
        src = node.get("src", "")
        return f"![{alt}]({src})"
    return inner


def _render_block(node, gdoc: bool = False, list_depth: int = 0) -> str:
    if _is_text(node):
        t = _clean_text(str(node))
        return t if t.strip() else ""
    name = node.name
    if name is None:
        return ""
    if name in ("script", "style", "noscript", "head", "meta", "link", "title", "nav", "footer"):
        return ""

    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        text = "".join(_render_inline(c, gdoc) for c in node.children).strip()
        if not text:
            return ""
        return f"\n{'#' * level} {text}\n"

    if name == "p":
        text = "".join(_render_inline(c, gdoc) for c in node.children).strip()
        if not text:
            return ""
        return f"\n{text}\n"

    if name in ("ul", "ol"):
        ordered = name == "ol"
        lines = []
        idx = 1
        for li in node.find_all("li", recursive=False):
            bullet = f"{idx}. " if ordered else "- "
            indent = "  " * list_depth
            text = "".join(
                _render_inline(c, gdoc)
                for c in li.children
                if _is_text(c) or (c.name not in ("ul", "ol"))
            ).strip()
            lines.append(f"{indent}{bullet}{text}")
            for sub in li.find_all(["ul", "ol"], recursive=False):
                lines.append(_render_block(sub, gdoc, list_depth + 1))
            idx += 1
        return "\n" + "\n".join(lines) + "\n"

    if name == "blockquote":
        text = "".join(
            _render_block(c, gdoc, list_depth) for c in node.children
        ).strip()
        quoted = "\n".join(f"> {ln}" for ln in text.splitlines())
        return f"\n{quoted}\n"

    if name == "pre":
        code_tag = node.find("code")
        lang = ""
        if code_tag:
            classes = code_tag.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls[9:]
                    break
            text = code_tag.get_text()
        else:
            text = node.get_text()
        return f"\n```{lang}\n{text}\n```\n"

    if name == "hr":
        return "\n---\n"

    if name == "table":
        rows = []
        for tr in node.find_all("tr"):
            cells = []
            for cell in tr.find_all(["td", "th"]):
                cells.append(
                    "".join(_render_inline(c, gdoc) for c in cell.children)
                    .strip()
                    .replace("\n", " ")
                )
            if cells:
                rows.append("| " + " | ".join(cells) + " |")
        if rows:
            ncols = rows[0].count("|") - 1
            sep = "| " + " | ".join("---" for _ in range(ncols)) + " |"
            rows.insert(1, sep)
            return "\n" + "\n".join(rows) + "\n"
        return ""

    if name in (
        "div", "section", "article", "main", "body", "html",
        "header", "figure", "figcaption", "[document]",
    ):
        return "".join(_render_block(c, gdoc, list_depth) for c in node.children)

    inline = "".join(_render_inline(c, gdoc) for c in node.children).strip()
    return inline


def html_to_md(html: str, gdoc: bool | None = None) -> str:
    """Convert HTML to GitHub-flavored markdown.

    Args:
        html: HTML source as a string.
        gdoc: If True, apply Google Docs export handling (unwraps google.com/url
            redirects, treats body as full content). If None (default), auto-
            detects via signature scan of the first 4KB.

    Returns:
        Markdown string with trailing newline.
    """
    if gdoc is None:
        gdoc = _is_gdoc(html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    root = _extract_content(soup) if not gdoc else (soup.body or soup)
    md = _render_block(root, gdoc=gdoc)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def html_to_text(html: str) -> str:
    """Convert HTML to plain text (tags stripped, whitespace normalized)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    root = _extract_content(soup)
    text = root.get_text(separator="\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def list_links(
    html: str,
    base_url: str | None = None,
    pattern: str | None = None,
) -> list[tuple[str, str]]:
    """Extract <a href> links from HTML, deduped.

    Args:
        html: HTML source as a string.
        base_url: If given, relative hrefs resolve against it.
        pattern: If given, regex filter on the resolved URL.

    Returns:
        List of (url, link_text) tuples, dedup-by-url.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        text = re.sub(r"\s+", " ", text)
        full = urljoin(base_url, href) if base_url else href
        if pattern and not re.search(pattern, full):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append((full, text))
    return out
