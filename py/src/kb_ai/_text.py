"""Lexical tokenisation shared by the paths that rank text without embeddings.

Retrieval's page selection and classify's catalog ordering both have to put the
most promising articles first before a prompt budget cuts the rest. Neither has
an embedding model, so both score token overlap -- and both need the same
tokenisation, because a title ranked one way here and another way there drops
different articles for the same question.
"""
from __future__ import annotations

import re

# Chinese, Japanese kana and the CJK compatibility block are written without word
# breaks, so each character is its own token; everything else is matched as a run
# of word characters, which \w resolves against Unicode -- Cyrillic, Greek and
# accented Latin included. A pattern restricted to [a-zA-Z0-9] tokenises a
# Chinese title to the empty set, which scores every article 0.0 and silently
# turns "rank by relevance" into "keep whatever came first".
_SCRIPTIO_CONTINUA = r"぀-ヿ㐀-䶿一-鿿豈-﫿"
_TOKEN_RE = re.compile(rf"[{_SCRIPTIO_CONTINUA}]|[^\W{_SCRIPTIO_CONTINUA}]+")


def tokens(text: str) -> set[str]:
    """Tokenise text for lexical overlap scoring."""
    return set(_TOKEN_RE.findall(text.lower()))


def overlap(a: set[str], b: set[str]) -> float:
    """Score two token sets, normalised by the smaller one.

    Dividing by the smaller set keeps a long summary from diluting a short
    title's match. Returns 0.0 when either side is empty.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))
