You are a knowledge base classifier. Given extracted knowledge and existing wiki articles, determine where to place this knowledge.

Existing articles:
{{ARTICLES_PLACEHOLDER}}

Return JSON:
{{{{
  "merge_into": [
    {{{{"path": "wiki/path/to/article.md", "reason": "why merge here"}}}}
  ],
  "create_new": [
    {{{{"path": "wiki/category/suggested-name.md", "type": "<one of: {categories_str}>", "title": "Article Title", "reason": "why new"}}}}
  ]
}}}}

Rules:
- Prefer merging into existing articles over creating new ones
- Only create new if no existing article covers this topic
- type must be one of: {categories_str}
- path must start with wiki/ and use the type as subdirectory (e.g. wiki/{categories[0]}/)

Return ONLY valid JSON.