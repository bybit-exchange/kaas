You are maintaining a knowledge base wiki article. Merge new information into the existing article.

Rules:
- Preserve the existing YAML frontmatter structure, but update 'updated' date and add every source listed under 'Sources' that the 'sources' list does not already contain, one item per path
- Rewrite the 'summary' line when the merge broadens what the article covers, so it still names what is actually here (one sentence, under 150 characters); add the line if it is missing
- If the article has a 'status' field (project articles), preserve it unless new information clearly indicates the project has been completed or archived — then update accordingly (active/completed/archived)
- Integrate new information naturally into existing sections
- Do not duplicate information already in the article
- Maintain consistent tone and formatting
- Add [[wikilinks]] for related concepts
- If new sections are needed, add them in a logical position

Superseded claims — where a source contradicts what the article already says:
- Replace the statement that no longer holds with the one that does, and put a note of what it used to say immediately after it, in the same section. Do not leave both values standing as though both were current, and do not attribute one to each version and stop there — the article has to say which value holds now
- The note is one line, in exactly this shape:

  The gateway targets 2 000 requests per second.

  [Superseded 2026-06-14 by raw/plan-v2.md: the earlier target was 1 200 requests per second.]

- The date is the date of the source that replaced the claim — its `- Date:` line in the material below — never today's date. The path after `by` is that same source's path, exactly as it is listed
- Only supersede using the source whose date is newer than every other date in this payload. If no source is the newest one — every source undated, or the newest date shared by two — leave the claim as it is and add no note
- Never supersede a value using a source older than the one the article already reflects
- Where the same claim is stated in more than one place, correct each one and note each one
- Every `[Superseded ...]` note already in the article must appear in your output word for word. The article's history is append-only: a new note goes immediately before the notes already at that spot, so they read newest first

Return the complete updated article (including frontmatter).
