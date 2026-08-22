"""Tests for the shared lexical tokeniser used by the ranking paths.

The CJK cases are the point of the module: a tokeniser that only recognises
ASCII word characters returns the empty set for a Chinese title, which collapses
every overlap score to zero and silently turns "rank by relevance" into a no-op.
"""
from __future__ import annotations

from kb_ai._text import overlap, tokens


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
