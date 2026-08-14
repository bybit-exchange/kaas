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

Return the complete updated article (including frontmatter).