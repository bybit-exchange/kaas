import json
import sys

from kb_ai.llm import completion


def _assemble_article_context(articles: list[dict]) -> str:
    """Dump full article contents as the RAG context block."""
    parts = []
    for a in articles:
        parts.append(f"### {a['title']} ({a['path']})\n{a.get('content', '')}")
    return "\n\n".join(parts)


def answer_question(
    question: str,
    articles: list[dict],
    model: str = "claude-opus-4-6",
) -> dict:
    """Answer a question using RAG over the knowledge base.

    Grounds the answer in the full contents of the candidate articles (no
    embeddings / vector chunking).
    """
    context = _assemble_article_context(articles)
    print(
        f"[RAG] {len(articles)} full articles, {len(context):,} chars",
        file=sys.stderr,
    )

    system = f"""You are a knowledge base assistant. Answer the question based on the provided knowledge articles.

<knowledge>
{context}
</knowledge>

Rules:
- Answer based ONLY on the provided knowledge
- Cite sources using [Article Title](./path) format
- If the knowledge doesn't contain enough info, say so
- Be concise and direct

Format your answer as markdown."""

    answer = completion(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ], max_tokens=4096).strip()
    sources = [{"title": a["title"], "path": a["path"]} for a in articles]

    return {"answer": answer, "sources": sources}


def run_query():
    from kb_ai.__main__ import respond
    input_data = json.loads(sys.stdin.read())
    question = input_data["question"]
    articles = input_data["articles"]
    model = input_data.get("model", "claude-opus-4-6")

    result = answer_question(question, articles, model=model)

    from kb_ai.llm import tracker
    tracker.print_summary()
    result["cost"] = tracker.summary()

    respond(True, data=result)
