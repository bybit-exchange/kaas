You are planning the article structure for a topic-focused knowledge base.

Topic: {topic}

The knowledge base contains extractions from {extraction_count} source documents. Below are the most frequent entities, topics, and concepts found across these documents.

Top entities (canonical name — occurrence count):
{entity_frequency}

Top topic tags (tag — occurrence count):
{topic_frequency}

Top concept titles:
{concept_titles}

Available article types: {categories_str}

Plan a set of thematic articles that organize this knowledge around the topic. Each article should synthesize information from multiple source documents into a coherent theme.

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
- Create 3-15 articles depending on the breadth of available material
- path must start with wiki/ and use the type as subdirectory
- path must use lowercase alphanumeric slugs with hyphens (e.g. wiki/concept/sun-wukong-overview.md)
- Focus on cross-cutting themes, not per-source-document articles
- The main topic entity should get a comprehensive overview article
- Related entities and themes each get their own article when there is enough material (>=3 source documents)
- type must be one of: {categories_str}