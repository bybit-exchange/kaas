"""Lexical tokenisation for ranking text without an embedding model.

Retrieval's page selection has to put the most promising articles first before a
prompt budget cuts the rest, and it has no embeddings to do that with, so it
scores token overlap instead. This lives in its own module because classify's
catalog ordering needs the same thing and still carries its own ASCII-only copy.
"""
from __future__ import annotations

import re

# Chinese, Japanese kana and the CJK compatibility block are written without word
# breaks, so each character is its own token; everything else is matched as a run
# of word characters, which \w resolves against Unicode -- Cyrillic, Greek and
# accented Latin included. A pattern restricted to [a-zA-Z0-9] tokenises a Chinese
# title to the empty set, which scores every article 0.0 and silently turns "rank
# by relevance" into "keep whatever came first".
#
# The underscore is excluded even though \w carries it: reference-table keys reach
# a catalog line as snake_case identifiers, and a question names one part of them
# ("the cooldown"), never the whole of cb_cooldown_sec.
_SCRIPTIO_CONTINUA = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_TOKEN_RE = re.compile(rf"[{_SCRIPTIO_CONTINUA}]|[^\W_{_SCRIPTIO_CONTINUA}]+")
_RUN_RE = re.compile(rf"[{_SCRIPTIO_CONTINUA}]+")
_WORD_RE = re.compile(rf"[^\W_{_SCRIPTIO_CONTINUA}]+")


def tokens(text: str) -> set[str]:
    """Tokenise text for lexical overlap scoring."""
    return set(_TOKEN_RE.findall(text.lower()))


def bigram_tokens(text: str) -> set[str]:
    """Tokenise for deciding whether two texts say the same thing.

    Same word tokens as tokens(), but each run of break-less script becomes its
    character bigrams instead of single characters. Single characters are the
    right unit for ranking, where a loose match only changes an ordering, and the
    wrong one for a decision: \u6570\u636e\u5b89\u5168 and \u5b89\u5168\u6570\u636e\u5e93 share every character of the
    shorter title, so on unigrams they score a perfect match, while on bigrams
    they share \u5b89\u5168 and \u6570\u636e out of four and no longer do. A one-character run has
    no bigram and is kept whole.

    Known limitation, inherited from _SCRIPTIO_CONTINUA: U+30FB (\u30fb) is inside the
    range, so a katakana phrase written with it yields bigrams straddling the
    separator. Narrowing the range would change tokens() too, and with it
    retrieval's ranking.
    """
    lowered = text.lower()
    out = set(_WORD_RE.findall(lowered))
    for run in _RUN_RE.findall(lowered):
        out.update(run[i:i + 2] for i in range(max(len(run) - 1, 1)))
    return out


def overlap(a: set[str], b: set[str]) -> float:
    """Score two token sets, normalised by the smaller one.

    Dividing by the smaller set keeps a long summary from diluting a short
    title's match. Returns 0.0 when either side is empty.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))
