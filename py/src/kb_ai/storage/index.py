from __future__ import annotations

from datetime import datetime

import yaml

from kb_ai.storage.store import KBStore


def update_markdown_index(store: KBStore, *, min_articles: int = 3) -> None:
    store.index_dir.mkdir(exist_ok=True)

    articles = []
    tags_map: dict[str, list[dict]] = {}

    for md_file in store.wiki_dir.rglob("*.md"):
        content = md_file.read_text()
        if not content.startswith("---"):
            continue
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            continue
        # Empty frontmatter loads as None and scalar frontmatter as str. Skip
        # like the other malformed cases above -- one bad article must not abort
        # the whole index rebuild.
        if not isinstance(fm, dict):
            continue

        rel_path = str(md_file.relative_to(store.base_dir))
        title = fm.get("title", md_file.stem)
        article_type = fm.get("type", "unknown")
        tags = fm.get("tags", [])
        status = fm.get("status", "")
        body = parts[2].strip()
        summary = body.split("\n\n")[0][:150].replace("\n", " ")

        articles.append({
            "title": title, "path": rel_path, "type": article_type,
            "tags": tags, "status": status, "summary": summary,
        })
        for tag in tags:
            tags_map.setdefault(str(tag), []).append({"title": title, "path": rel_path})

    master = "# Knowledge Base Index\n\n"
    for a in sorted(articles, key=lambda x: x["title"]):
        status_marker = f" [{a['status']}]" if a.get("status") else ""
        master += f"- [{a['title']}]({a['path']}){status_marker} — {a['summary']}\n"
    (store.index_dir / "master-index.md").write_text(master)

    # Split topic index by frequency.
    primary_tags = [(tag, arts) for tag, arts in tags_map.items() if len(arts) >= min_articles]
    longtail_tags = [(tag, arts) for tag, arts in tags_map.items() if len(arts) < min_articles]

    # Primary: sort by article count desc, tie-break by tag name asc.
    primary_tags.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    # Longtail: alphabetical.
    longtail_tags.sort(key=lambda kv: kv[0])

    primary_md = f"# Topic Index\n\nTags with at least {min_articles} articles, sorted by frequency.\n\n"
    for tag, arts in primary_tags:
        primary_md += f"## {tag} ({len(arts)})\n\n"
        for a in sorted(arts, key=lambda x: x["title"]):
            primary_md += f"- [{a['title']}]({a['path']})\n"
        primary_md += "\n"
    (store.index_dir / "topic-index.md").write_text(primary_md)

    longtail_md = f"# Topic Index — Long Tail\n\nTags with fewer than {min_articles} articles.\n\n"
    for tag, arts in longtail_tags:
        longtail_md += f"## {tag} ({len(arts)})\n\n"
        for a in sorted(arts, key=lambda x: x["title"]):
            longtail_md += f"- [{a['title']}]({a['path']})\n"
        longtail_md += "\n"
    (store.index_dir / "topic-index-longtail.md").write_text(longtail_md)


def update_timeline(store: KBStore, compiled_sources: list[str]) -> None:
    store.index_dir.mkdir(exist_ok=True)
    timeline_path = store.index_dir / "timeline.md"

    if not timeline_path.exists():
        timeline_path.write_text("# Knowledge Timeline\n\n")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entries = f"\n## {now}\n\n"
    for src in compiled_sources:
        entries += f"- Compiled: `{src}`\n"

    with open(timeline_path, "a") as f:
        f.write(entries)
