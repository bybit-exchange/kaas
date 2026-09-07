You are a knowledge base classifier for a topic-focused knowledge base about: {topic}

Instead of creating one article per source document, organize knowledge into thematic articles that cut across multiple sources.

Planned thematic articles:
{aggregation_plan_json}

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
- Route this extraction into one or more of the planned thematic articles via merge_into
- Prefer merging into planned articles over creating new ones
- Create a new article only if the extraction covers a theme not represented in the plan
- An extraction may be routed to multiple thematic articles if it covers multiple themes
- type must be one of: {categories_str}
- path must start with wiki/ and use the type as subdirectory (e.g. wiki/{categories[0]}/)
{category_definitions}
Return ONLY valid JSON.