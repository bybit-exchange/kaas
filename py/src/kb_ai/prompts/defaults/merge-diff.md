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
    }
  ]
}

Rules:
- Do NOT reproduce existing content — only describe additions
- "append_to_section": append content at the end of the named section (before the next heading)
- "new_section": insert a new section after the specified existing section
- If ALL information is already in the article, return: {"patches": []}
- Use [[wikilinks]] in content
- Keep patches focused and concise

Return ONLY valid JSON, no markdown fencing.