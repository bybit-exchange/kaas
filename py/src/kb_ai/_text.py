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
_SCRIPTIO_CONTINUA = r"぀-ヿ㐀-䶿一-鿿豈-﫿"
_TOKEN_RE = re.compile(rf"[{_SCRIPTIO_CONTINUA}]|[^\W_{_SCRIPTIO_CONTINUA}]+")
_RUN_RE = re.compile(rf"[{_SCRIPTIO_CONTINUA}]+")
_CHUNK_RE = re.compile(rf"[{_SCRIPTIO_CONTINUA}]+|[^\W_{_SCRIPTIO_CONTINUA}]+")


def tokens(text: str) -> set[str]:
    """Tokenise text for lexical overlap scoring."""
    return set(_TOKEN_RE.findall(text.lower()))


def bigram_sequence(text: str) -> list[str]:
    """Tokenise for deciding whether two texts say the same thing, in order.

    Same word tokens as tokens(), but each run of break-less script becomes its
    character bigrams instead of single characters. Single characters are the
    right unit for ranking, where a loose match only changes an ordering, and the
    wrong one for a decision: 数据安全 and 安全数据库 share every character of the
    shorter title, so on unigrams they score a perfect match, while on bigrams
    they share 安全 and 数据 -- two of the shorter title's three -- and no longer
    do. A one-character run has no bigram and is kept whole.

    Reading order is preserved, and repeats are kept, because a caller comparing
    two titles needs both: as sets, 腾讯云到阿里云迁移方案 and 阿里云到腾讯云迁移方案
    are identical while saying opposite things.

    "&" is read as the word it stands for. Nine of the duplicate pairs in
    data/kb-knowledge are one article written once with "&" and once with "And",
    and without this they differ on BOTH sides -- which core.classify reads as two
    different subjects rather than one rewording. tokens() deliberately does not
    do this: it would move retrieval's ranking, which is outside this change.

    Known limitation, inherited from _SCRIPTIO_CONTINUA: U+30FB (・) is inside the
    range, so a katakana phrase written with it yields bigrams straddling the
    separator. Narrowing the range would change tokens() too, and with it
    retrieval's ranking.
    """
    out: list[str] = []
    for chunk in _CHUNK_RE.findall(text.lower().replace("&", " and ")):
        if _RUN_RE.fullmatch(chunk):
            out.extend(chunk[i:i + 2] for i in range(max(len(chunk) - 1, 1)))
        else:
            out.append(chunk)
    return out


def bigram_tokens(text: str) -> set[str]:
    """bigram_sequence as a set, for scoring rather than ordering."""
    return set(bigram_sequence(text))


def overlap(a: set[str], b: set[str]) -> float:
    """Score two token sets, normalised by the smaller one.

    Dividing by the smaller set keeps a long summary from diluting a short
    title's match. Returns 0.0 when either side is empty.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))
