You are maintaining a large knowledge base wiki article. The article is too large to rewrite entirely.
Instead, output ONLY a JSON object describing the content changes to apply.
Frontmatter (sources, updated date) will be updated automatically — do NOT include them.

{
  "patches": [
    {
      "action": "append_to_section",
      "section": "## Section Heading",
      "content": "New paragraph or bullet points to append..."
    },
    {
      "action": "new_section",
      "after": "## Existing Section",
      "heading": "## New Section Title",
      "content": "Section body..."
    },
    {
      "action": "supersede",
      "anchor": "the exact existing article text that no longer holds",
      "replacement": "what stands now",
      "by": "raw/path/to/the-newer-source.md",
      "was": "the claim that stopped being true, as the record should state it"
    }
  ]
}

Rules:
- Do NOT reproduce existing content — only describe additions
- "append_to_section": append content at the end of the named section (before the next heading)
- "new_section": insert a new section after the specified existing section
- "supersede": correct an existing statement that a newer source contradicts. Only for a contradiction — information the article does not have yet is an addition, not a supersession
- If ALL information is already in the article, return: {"patches": []}
- Use [[wikilinks]] in content
- Keep patches focused and concise

Using "supersede" — these four fields and no others:
- "anchor" must occur in the article exactly once. Include enough surrounding text to make it unique: the match is exact, nothing is normalized, and an anchor found twice or not at all is discarded
- Where the same claim is stated in more than one place, emit one action per occurrence
- "by" must name the source in this payload whose date is newer than every other date here. If no source is the newest one — every source undated, or the newest date shared by two — leave the claim alone and emit no action for it
- Never supersede a value using a source older than the one the article already reflects
- "was" is required and carries the old value: it becomes the article's record of what the claim used to be. "replacement" may be empty, which withdraws the claim and leaves that record standing in its place
- Do NOT write the bracketed note yourself. It is rendered from "by", "was" and that source's own date

Return ONLY valid JSON, no markdown fencing.
