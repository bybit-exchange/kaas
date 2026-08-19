from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from kb_ai._fadvise import read_text_and_evict
from kb_ai._frontmatter import split_frontmatter
from kb_ai.storage.index import SUMMARY_MAX_CHARS
from kb_ai.storage.store import KBStore

STUB_SENTINEL = "<!-- kb:stub -->"
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Marks a title list cut short, mirroring storage.index._KEYS_ELLIPSIS: a
# half-written title would read as a different article.
_SUMMARY_ELLIPSIS = ", …"


def _slug(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _extract_target(wikilink_body: str) -> str:
    if "|" in wikilink_body:
        return wikilink_body.split("|", 1)[0].strip()
    return wikilink_body.strip()


def _article_title(md_path: Path, content: str) -> str:
    split = split_frontmatter(content)
    if split is not None:
        try:
            fm = yaml.safe_load(split[0]) or {}
            title = fm.get("title")
            if title:
                return str(title)
        except yaml.YAMLError:
            pass
    return md_path.stem


def _is_stub(content: str) -> bool:
    split = split_frontmatter(content)
    if split is None:
        return False
    return split[1].lstrip().startswith(STUB_SENTINEL)


def _existing_created(path: Path) -> str | None:
    if not path.exists():
        return None
    content = path.read_text()
    split = split_frontmatter(content)
    if split is None:
        return None
    try:
        fm = yaml.safe_load(split[0]) or {}
    except yaml.YAMLError:
        return None
    created = fm.get("created")
    if created is None:
        return None
    return str(created)


def _stub_summary(mentions: int, sources: list[tuple[str, str]]) -> str:
    """The stub's catalog line: who, how often, and in which articles.

    A stub declares its own summary because storage.index._derive_summary
    otherwise falls back to the body's first paragraph -- STUB_SENTINEL -- so
    every person occupied a catalog line reading "<!-- kb:stub -->", routing
    nothing while still costing prompt budget. The article titles are the
    routing terms: they are what a page selection or a topic filter can match a
    question against.

    Capped at the catalog's own SUMMARY_MAX_CHARS, keeping whole titles only:
    a person mentioned everywhere must not monopolise a prompt that carries the
    entire catalog. The name is deliberately absent -- every consumer of a
    summary renders the title alongside it (render_catalog_line, the master
    index line, classify's article list), so repeating it here would only spend
    budget that the titles use better.
    """
    head = f"Person stub, {mentions} mention(s)"
    out = head
    for i, (title, _path) in enumerate(sources):
        # Reserve room for the cut marker while titles are still pending, so
        # appending it later cannot push the summary past the budget.
        limit = SUMMARY_MAX_CHARS - (
            len(_SUMMARY_ELLIPSIS) if i < len(sources) - 1 else 0)
        candidate = f"{out} in: {title}" if out == head else f"{out}, {title}"
        if len(candidate) > limit:
            return out if out == head else f"{out}{_SUMMARY_ELLIPSIS}"
        out = candidate
    return out


def _format_stub(canonical: str, mentions: int, aliases_seen: list[str],
                 sources: list[tuple[str, str]], created: str, updated: str) -> str:
    sources_yaml = "\n".join(f"  - {path}" for _, path in sources)
    aliases_inline = ", ".join(f'"{a}"' for a in aliases_seen)
    mentions_block = "\n".join(
        f"- [{title}]({path})" for title, path in sources
    )
    # Dumped rather than interpolated: titles reach here from article
    # frontmatter, so a quote or a colon in one would break the YAML.
    summary_yaml = yaml.safe_dump(
        {"summary": _stub_summary(mentions, sources)},
        allow_unicode=True, default_flow_style=False, width=10**6,
    ).strip()
    return (
        f"---\n"
        f'title: "{canonical}"\n'
        f"type: person\n"
        f"{summary_yaml}\n"
        f"mentions: {mentions}\n"
        f"aliases: [{aliases_inline}]\n"
        f"sources:\n{sources_yaml}\n"
        f"created: {created}\n"
        f"updated: {updated}\n"
        f"---\n"
        f"{STUB_SENTINEL}\n\n"
        f"{canonical} is referenced in {mentions} articles across the knowledge base.\n"
        f"A full biography has not yet been written.\n\n"
        f"### Where {canonical} appears\n\n"
        f"{mentions_block}\n"
    )


def update_people_stubs(store: KBStore, people_cfg: list[dict]) -> None:
    """Scan wiki/ for [[Name]] wikilinks and generate stub pages for allowlisted people.

    Args:
        store: the KB store.
        people_cfg: list of {canonical: str, aliases: [str, ...]} entries from kb.toml.
    """
    if not people_cfg:
        return

    alias_to_canonical: dict[str, tuple[str, str]] = {}
    for person in people_cfg:
        canonical = person["canonical"]
        for alias in person.get("aliases", []):
            alias_to_canonical[alias.lower()] = (canonical, alias)

    mentions: dict[str, int] = {}
    aliases_seen: dict[str, set[str]] = {}
    sources: dict[str, list[tuple[str, str]]] = {}
    sources_seen: dict[str, set[str]] = {}

    wiki_dir = store.wiki_dir
    if not wiki_dir.exists():
        return

    for md_file in sorted(wiki_dir.rglob("*.md")):
        try:
            rel_parts = md_file.relative_to(wiki_dir).parts
        except ValueError:
            continue
        if rel_parts and rel_parts[0] == "people":
            continue

        content = read_text_and_evict(md_file)
        title = _article_title(md_file, content)
        rel_path = str(md_file.relative_to(store.base_dir))

        for match in WIKILINK_RE.finditer(content):
            target = _extract_target(match.group(1))
            key = target.lower()
            entry = alias_to_canonical.get(key)
            if entry is None:
                continue
            canonical, original_alias = entry
            mentions[canonical] = mentions.get(canonical, 0) + 1
            aliases_seen.setdefault(canonical, set()).add(original_alias)
            if rel_path not in sources_seen.setdefault(canonical, set()):
                sources_seen[canonical].add(rel_path)
                sources.setdefault(canonical, []).append((title, rel_path))

    people_dir = wiki_dir / "people"
    today = date.today().isoformat()
    for person in people_cfg:
        canonical = person["canonical"]
        if canonical not in mentions:
            continue
        stub_path = people_dir / f"{_slug(canonical)}.md"

        if stub_path.exists():
            existing = stub_path.read_text()
            if not _is_stub(existing):
                continue

        created = _existing_created(stub_path) or today
        people_dir.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(_format_stub(
            canonical=canonical,
            mentions=mentions[canonical],
            aliases_seen=sorted(aliases_seen[canonical]),
            sources=sorted(sources[canonical], key=lambda s: s[0]),
            created=created,
            updated=today,
        ))
