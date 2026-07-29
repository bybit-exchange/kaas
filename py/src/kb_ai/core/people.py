from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from kb_ai.storage.store import KBStore

STUB_SENTINEL = "<!-- kb:stub -->"
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


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
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
                title = fm.get("title")
                if title:
                    return str(title)
            except yaml.YAMLError:
                pass
    return md_path.stem


def _is_stub(content: str) -> bool:
    if not content.startswith("---"):
        return False
    parts = content.split("---", 2)
    if len(parts) < 3:
        return False
    body = parts[2].lstrip()
    return body.startswith(STUB_SENTINEL)


def _existing_created(path: Path) -> str | None:
    if not path.exists():
        return None
    content = path.read_text()
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    created = fm.get("created")
    if created is None:
        return None
    return str(created)


def _format_stub(canonical: str, mentions: int, aliases_seen: list[str],
                 sources: list[tuple[str, str]], created: str, updated: str) -> str:
    sources_yaml = "\n".join(f"  - {path}" for _, path in sources)
    aliases_inline = ", ".join(f'"{a}"' for a in aliases_seen)
    mentions_block = "\n".join(
        f"- [{title}]({path})" for title, path in sources
    )
    return (
        f"---\n"
        f'title: "{canonical}"\n'
        f"type: person\n"
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

        content = md_file.read_text()
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
