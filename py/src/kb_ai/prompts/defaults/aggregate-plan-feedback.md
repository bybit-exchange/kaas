You are refining the article plan for a topic-focused knowledge base.

Topic: {topic}

Below is the initial article plan:
{first_round_articles}

Below are the frequency tables from the source documents:

Top entities (canonical name — occurrence count):
{entity_frequency}

Top topic tags (tag — occurrence count):
{topic_frequency}

Top concept titles:
{concept_titles}

Available article types: {categories_str}

Review the initial plan against the frequency data and improve it:
1. Identify high-frequency entities, topics, or concepts that are NOT adequately covered by any article.
2. Identify articles that are too narrow or redundant and could be merged.
3. Ensure the main topic entity has a comprehensive overview article.
4. Check that major themes (appearing in >=3 source documents) have dedicated articles.

Return the FULL refined plan as JSON — every article that should be in the final plan must appear in your output, including articles from the original plan that need no changes.

Return JSON:
{{{{
  "articles": [
    {{{{
      "path": "wiki/<type>/suggested-slug.md",
      "type": "<one of: {categories_str}>",
      "title": "Article Title",
      "description": "1-2 sentence description of what this article should cover"
    }}}}
  ]
}}}}

Rules:
- Return 3-15 articles
- path must start with wiki/ and use the type as subdirectory
- path must use lowercase alphanumeric slugs with hyphens
- type must be one of: {categories_str}
- Do NOT return duplicate paths
