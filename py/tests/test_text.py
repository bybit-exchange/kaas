"""Tests for the shared lexical tokeniser used by the ranking paths.

The CJK cases are the point of the module: a tokeniser that only recognises
ASCII word characters returns the empty set for a Chinese title, which collapses
every overlap score to zero and silently turns "rank by relevance" into a no-op.
"""
from __future__ import annotations

import pytest

from kb_ai._text import bigram_tokens, overlap, tokens

# The ends of the four blocks the tokeniser reads as break-less script, and word
# characters just outside them. Pinned here because nothing else in the suite would
# notice that range moving, and it can move without anyone editing it -- the comment
# on _SCRIPTIO_CONTINUA in _text.py says how.
#
# The expectations are escapes rather than the characters they denote: as
# characters, one NFKC pass over the tree would rewrite them and the range they pin
# in the same direction, and the mismatch would stay green.
_BREAK_LESS_ENDPOINTS = [
    "\u3040", "\u30ff",  # hiragana, katakana and their punctuation
    "\u3400", "\u4dbf",  # CJK unified ideographs extension A
    "\u4e00", "\u9fff",  # CJK unified ideographs
    "\uf900", "\ufaff",  # CJK compatibility ideographs
]

# Word characters just outside those blocks, which have to keep joining their
# neighbours into one token. U+AC00 earns its place: the compatibility block's lower
# bound is the one an NFKC rewrite drags down, and Hangul is the largest stretch of
# word characters it swallows on the way.
#
# There is deliberately no probe between U+4DBF and U+4E00: that gap holds only
# hexagram symbols, which \w does not match, so a bound widened there is not
# observable through the tokeniser.
_WORD_CHARS_OUTSIDE = [
    "\u3005",  # ideographic iteration mark, below the kana block
    "\u3105",  # bopomofo, between the kana block and extension A
    "\ua000",  # Yi syllable, above the unified block
    "\uac00",  # Hangul syllable, above the unified block
    "\ufb00",  # Latin ligature, above the compatibility block
]


@pytest.mark.parametrize("char", _BREAK_LESS_ENDPOINTS)
def test_tokens_gives_each_character_of_the_break_less_blocks_its_own_token(char):
    assert tokens(f"a{char}b") == {"a", char, "b"}


@pytest.mark.parametrize("char", _WORD_CHARS_OUTSIDE)
def test_tokens_joins_a_word_character_outside_the_break_less_blocks(char):
    assert tokens(f"a{char}b") == {f"a{char}b"}


def test_tokens_splits_ascii_words_on_punctuation():
    assert tokens("Circuit-breaker cooldown: tuning!") == {"circuit", "breaker",
                                                           "cooldown", "tuning"}


def test_tokens_lowercases():
    assert tokens("Worker QUEUE") == {"worker", "queue"}


def test_tokens_gives_each_chinese_character_its_own_token():
    # Chinese is written without word breaks, so per-character tokens are the
    # only overlap signal available without a segmenter.
    assert tokens("熔断器") == {"熔", "断", "器"}


def test_tokens_splits_an_identifier_into_its_parts():
    # Reference-table keys reach the catalog line as snake_case identifiers, and a
    # question names the part, not the whole: "the cooldown" has to reach the
    # article whose keys carry cb_cooldown_sec.
    assert tokens("cb_cooldown_sec") == {"cb", "cooldown", "sec"}


def test_tokens_keeps_non_ascii_alphabets_as_words():
    assert tokens("Café Привет") == {"café", "привет"}


def test_tokens_mixes_scripts_in_one_string():
    assert tokens("熔断器 cooldown") == {"熔", "断", "器", "cooldown"}


def test_tokens_of_empty_text_is_empty():
    assert tokens("   ...   ") == set()


def test_overlap_is_one_for_identical_sets():
    assert overlap({"a", "b"}, {"a", "b"}) == 1.0


def test_overlap_normalises_by_the_smaller_set():
    # 1 shared token, smaller set has 2 -> 0.5, so a long summary cannot dilute
    # a short title's match.
    assert overlap({"a", "b"}, {"a", "x", "y", "z"}) == 0.5


def test_overlap_is_zero_when_either_set_is_empty():
    assert overlap(set(), {"a"}) == 0.0
    assert overlap({"a"}, set()) == 0.0


def test_overlap_of_chinese_query_and_title_is_nonzero():
    assert overlap(tokens("熔断器冷却时间调优"), tokens("熔断器冷却时间怎么调")) > 0.0


def test_bigram_tokens_pairs_adjacent_characters_of_a_chinese_run():
    assert bigram_tokens("数据安全") == {"数据", "据安", "安全"}


def test_bigram_tokens_separates_titles_that_share_every_character():
    """The reason the function exists. Whether that separation clears the dedup
    threshold is core.classify's business and is asserted there -- here the claim
    is only that the two titles stop being subsets of one another."""
    assert bigram_tokens("数据安全") == {"数据", "据安", "安全"}
    assert bigram_tokens("安全数据库") == {"安全", "全数", "数据", "据库"}
    assert tokens("数据安全") < tokens("安全数据库")


def test_bigram_tokens_pairs_kana_runs_too():
    """The range covers kana, so a Japanese title is bigrammed rather than left as
    one word token."""
    assert bigram_tokens("ひらがな") == {"ひら", "らが", "がな"}


def test_bigram_tokens_keeps_a_one_character_run_whole():
    """A run with no bigram must not vanish, or a title made of single characters
    between Latin words is unmatchable against itself."""
    assert bigram_tokens("网") == {"网"}
    assert bigram_tokens("AI 网 gateway") == {"ai", "网", "gateway"}


def test_bigram_tokens_keeps_word_tokens_as_words():
    assert bigram_tokens("Cost-Review 2026-01") == {"cost", "review", "2026", "01"}
