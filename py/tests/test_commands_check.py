"""Tests for the kb-ai check CLI: the operator entry point to F3, F5 and grounding.

The checks were reachable only from tests and from a python -c, which is how a
check rots. This command is the surface that makes them runnable; it spends
nothing and rewrites nothing, so it is safe to point at someone else's KB.
"""
from __future__ import annotations

import json
from pathlib import Path

from kb_ai.commands import check as check_cmd
from kb_ai.core import merge as mg
from kb_ai.core.extract import ExtractionResult
from kb_ai.prompts import NoActivePromptError
from kb_ai.storage import extraction as exl
from kb_ai.storage.store import KBStore, _compute_checksum


def _kb(base: Path, docs: dict[str, str]) -> KBStore:
    store = KBStore(str(base))
    for rel, content in docs.items():
        store.write_raw(rel, content)
    return store


def _extract(store: KBStore, rel: str, *, checksum: str | None = None) -> None:
    exl.persist(store, rel, ExtractionResult(summary=f"summary of {rel}"),
                source_checksum=checksum or _compute_checksum(store.read_raw(rel)),
                extract_model="m")


def _derived(base: Path, parent: KBStore, docs: list[str]) -> Path:
    base.mkdir(parents=True)
    (base / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "source_kb": str(parent.base_dir),
        "slug": "topic",
        "documents": [{"rel_path": rel,
                       "checksum": _compute_checksum(parent.read_raw(rel)),
                       "size_bytes": 1} for rel in docs],
    }))
    return base


def _run(monkeypatch, argv) -> dict:
    out: list[str] = []
    monkeypatch.setattr("builtins.print",
                        lambda *a, **kw: out.append(str(a[0])) if a else None)
    check_cmd.run_check(argv)
    return json.loads(out[-1])


def test_defaults_kb_to_dot_kaas():
    assert check_cmd.build_parser().parse_args([]).kb == "./.kaas"


def test_a_kb_whose_extractions_all_match(monkeypatch, tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body", "raw/nested/b.md": "b body"})
    _extract(store, "raw/a.md")
    _extract(store, "raw/nested/b.md")

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    assert resp["ok"] is True
    ext = resp["data"]["extractions"]
    assert ext["matches"]["items"] == ["raw/a.md", "raw/nested/b.md"]
    assert ext["matches"]["count"] == 2
    assert ext["missing"]["items"] == [] and ext["mismatched"]["items"] == []
    assert "2 match" in ext["summary"]


def test_a_mismatched_extraction_carries_the_document_and_the_reason(monkeypatch,
                                                                    tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md", checksum="0" * 16)

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    mismatched = resp["data"]["extractions"]["mismatched"]
    assert mismatched["count"] == 1 and len(mismatched["items"]) == 1
    assert mismatched["items"][0]["document"] == "raw/a.md"
    assert "document hashes to" in mismatched["items"][0]["reason"]


def test_a_missing_extraction_is_reported_without_being_called_a_fault(monkeypatch,
                                                                     tmp_path):
    """F3: the next compile pays for a missing extraction once. Not an error."""
    _kb(tmp_path, {"raw/a.md": "a body"})

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    assert resp["ok"] is True
    assert resp["data"]["extractions"]["missing"]["items"] == [
        {"document": "raw/a.md", "reason": "missing"}]


def test_a_kb_that_was_never_derived_reports_the_parent_check_as_unknown(monkeypatch,
                                                                        tmp_path):
    """F5 degrades rather than failing, so one command covers both kinds of KB."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    parent = resp["data"]["parent"]
    assert parent["verdict"] == "unknown"
    assert "manifest.json" in parent["reason"]


def test_a_derived_kb_reports_both_checks(monkeypatch, tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body", "raw/b.md": "b body"})
    derived_dir = _derived(tmp_path / "derived", parent, ["raw/a.md", "raw/b.md"])
    derived = KBStore(str(derived_dir))
    derived.write_raw("raw/a.md", "a body")
    derived.write_raw("raw/b.md", "b body")
    _extract(derived, "raw/a.md")
    _extract(derived, "raw/b.md")

    resp = _run(monkeypatch, ["--kb", str(derived_dir)])

    assert resp["data"]["extractions"]["matches"]["items"] == ["raw/a.md", "raw/b.md"]
    assert resp["data"]["parent"]["verdict"] == "in_sync"
    assert resp["data"]["parent"]["in_sync"]["items"] == ["raw/a.md", "raw/b.md"]
    assert resp["data"]["parent"]["source_kb"] == str(parent.base_dir)


def test_a_document_changed_in_the_parent_is_named(monkeypatch, tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived_dir = _derived(tmp_path / "derived", parent, ["raw/a.md"])
    parent.write_raw("raw/a.md", "a body, revised")

    resp = _run(monkeypatch, ["--kb", str(derived_dir)])

    assert resp["data"]["parent"]["verdict"] == "changed_in_parent"
    assert resp["data"]["parent"]["changed_in_parent"]["items"] == ["raw/a.md"]


def test_both_summaries_are_printed_for_an_operator_to_read(tmp_path, capsys):
    """Not via _run: that one replaces print(), which is where these lines go."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")

    check_cmd.run_check(["--kb", str(tmp_path)])

    captured = capsys.readouterr()
    assert "1 match" in captured.err
    assert "unknown" in captured.err
    assert json.loads(captured.out)["ok"] is True


def _composed(store: KBStore, rel: str, *, extract: str, write: str) -> None:
    state = store.load_compile_state()
    state[rel] = {"checksum": _compute_checksum(store.read_raw(rel)),
                  "compiled_at": "2026-08-08T10:00:00",
                  "prompt_version": extract, "write_prompt_version": write}
    store.save_compile_state(state)


def test_check_names_the_documents_behind_the_write_prompt(monkeypatch, tmp_path):
    """The whole point of the write-phase version: editing merge-rewrite.md
    invalidates nothing, so the next compile is a no-op and reports nothing. This
    is where an operator finds out, for free, at any time."""
    store = _kb(tmp_path, {"raw/a.md": "a body", "raw/b.md": "b body"})
    _extract(store, "raw/a.md")
    _extract(store, "raw/b.md")
    _composed(store, "raw/a.md", extract=exl.current_prompt_version(),
              write="an-older-write-prompt")
    _composed(store, "raw/b.md", extract=exl.current_prompt_version(),
              write=mg.write_prompt_version())

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    wiki = resp["data"]["wiki"]
    assert wiki["behind_write_prompt"]["items"] == ["raw/a.md"]
    assert wiki["behind_extract_prompt"]["items"] == []
    assert "1 behind the write prompt" in wiki["summary"]


def test_check_reports_an_empty_lag_for_a_kb_that_was_never_compiled(monkeypatch,
                                                                    tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    empty = {"count": 0, "items": [], "truncated": False}
    assert resp["data"]["wiki"] == {
        "behind_extract_prompt": empty, "behind_write_prompt": empty,
        "extract_first_run": False, "write_first_run": False,
        "summary": "0 behind the extract prompt, 0 behind the write prompt"}


def test_an_unreadable_prompt_set_still_reports_the_checks_that_do_not_need_it(
        monkeypatch, tmp_path, capsys):
    """F3 and F5 depend on no prompt. Refusing to run them because a prompt
    directory is broken would withhold answers that are still available."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    _composed(store, "raw/a.md", extract="e0", write="w0")

    def boom():
        raise NoActivePromptError("prompt file not found: merge-diff")

    monkeypatch.setattr(check_cmd, "write_prompt_version", boom)

    check_cmd.run_check(["--kb", str(tmp_path)])

    captured = capsys.readouterr()
    resp = json.loads(captured.out)
    assert resp["ok"] is True
    assert resp["data"]["extractions"]["matches"]["items"] == ["raw/a.md"]
    assert resp["data"]["wiki"]["behind_write_prompt"]["items"] == []
    assert "write prompt version unavailable" in resp["data"]["wiki"]["summary"]
    assert "merge-diff" in captured.err


# ── grounding (issue #42) ───────────────────────────────────────────
#
# The third check on the same surface: it spends nothing, so it belongs beside F3
# and F5 rather than behind a compile that only runs when there is other work.

def _article(store: KBStore, rel: str, body: str, sources: list[str]) -> None:
    lines = "\n".join(f"  - {s}" for s in sources)
    store.write_article(rel, f"---\ntitle: \"A\"\ntype: concept\n"
                             f"sources:\n{lines}\n---\n\n{body}\n")


def test_check_names_the_unsourced_items_and_the_line_they_are_on(monkeypatch,
                                                                 tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    _article(store, "wiki/c.md", "| `Auth` | bool |\n", ["raw/a.md"])

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    found = resp["data"]["grounding"]
    assert found["checked"]["items"] == ["wiki/c.md"]
    assert found["unsourced"]["items"] == [
        {"article": "wiki/c.md", "name": "Auth", "line": "| `Auth` | bool |"}]
    assert "1 unsourced" in found["summary"]


def test_check_reports_a_clean_wiki_as_clean(monkeypatch, tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    # _extract stores "summary of raw/a.md", so this name is in the material.
    _article(store, "wiki/c.md", "| `summary` | text |\n", ["raw/a.md"])

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    assert resp["data"]["grounding"]["unsourced"]["items"] == []
    assert resp["data"]["grounding"]["skipped"]["items"] == []


def test_check_carries_the_reason_an_article_could_not_be_checked(monkeypatch,
                                                                 tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _article(store, "wiki/c.md", "| `Auth` | bool |\n", ["raw/a.md"])

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    skipped = resp["data"]["grounding"]["skipped"]
    assert skipped["count"] == 1 and len(skipped["items"]) == 1
    assert skipped["items"][0]["article"] == "wiki/c.md"
    assert "missing" in skipped["items"][0]["reason"]
    # Not counted as a clean article, and not counted as a finding either.
    assert resp["data"]["grounding"]["checked"]["items"] == []
    assert resp["data"]["grounding"]["unsourced"]["items"] == []


def test_a_kb_with_no_wiki_yet_reports_an_empty_grounding_check(monkeypatch,
                                                               tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    empty = {"count": 0, "items": [], "truncated": False}
    assert resp["data"]["grounding"] == {
        "checked": empty, "unsourced": empty, "skipped": empty,
        "summary": "no articles"}


def test_the_grounding_summary_is_printed_for_an_operator_to_read(tmp_path, capsys):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    _article(store, "wiki/c.md", "| `Auth` | bool |\n", ["raw/a.md"])

    check_cmd.run_check(["--kb", str(tmp_path)])

    assert "[check] grounding: 1 unsourced" in capsys.readouterr().err


def test_the_command_neither_spends_nor_rewrites(monkeypatch, tmp_path):
    """F3 and F5 are read-only by design; the entry point must not change that."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    _run(monkeypatch, ["--kb", str(tmp_path)])

    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_capped_reports_the_true_total_alongside_the_items_it_shows():
    """A truncated list must not be readable as a complete one.

    The whole point of the cap is that the payload stays small on a large KB, and
    the whole risk of a cap is that the reader takes 20 rows for the whole story.
    count is the real total whatever the limit does.
    """
    got = check_cmd._capped(list(range(100)), 20)

    assert got["count"] == 100
    assert got["items"] == list(range(20))
    assert got["truncated"] is True


def test_capped_does_not_claim_truncation_it_did_not_perform():
    under = check_cmd._capped(["a", "b"], 20)
    assert under == {"count": 2, "items": ["a", "b"], "truncated": False}

    # Exactly at the limit: nothing was dropped, so nothing may say otherwise.
    exact = check_cmd._capped(["a", "b"], 2)
    assert exact["truncated"] is False and exact["items"] == ["a", "b"]


def test_capped_treats_a_zero_limit_as_no_limit():
    """The escape hatch for anyone who needs every row."""
    got = check_cmd._capped(list(range(50)), 0)

    assert got["count"] == 50 and len(got["items"]) == 50
    assert got["truncated"] is False


def test_the_limit_defaults_to_a_value_that_keeps_the_payload_readable():
    assert check_cmd.build_parser().parse_args([]).limit == 20


def test_a_negative_limit_is_rejected_at_the_boundary(capsys):
    """Silently reinterpreting -1 as "no limit" would hand back the 482KB the cap
    exists to prevent, to someone who thought they were shrinking the output."""
    try:
        check_cmd.build_parser().parse_args(["--limit", "-1"])
    except SystemExit:
        # Pinned to the validator's own wording. "limit" alone would also match
        # argparse's "unrecognized arguments: --limit -1", so this assertion
        # would pass on a build where the option does not exist at all.
        assert "negative" in capsys.readouterr().err
    else:
        raise AssertionError("a negative --limit was accepted")


def test_a_large_finding_list_is_capped_in_the_payload(monkeypatch, tmp_path):
    """On a real KB this list ran to 1024 rows of identical reason, which is how
    one diagnostic command came to print 482KB of JSON."""
    # Documents written with no extractions: every one lands in missing.
    _kb(tmp_path, {f"raw/d{i:03}.md": f"body {i}" for i in range(25)})

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    missing = resp["data"]["extractions"]["missing"]
    assert missing["count"] == 25
    assert len(missing["items"]) == 20
    assert missing["truncated"] is True
    # The summary still speaks for the whole set, not for the shown slice.
    assert "25 missing" in resp["data"]["extractions"]["summary"]


def test_limit_zero_restores_every_row(monkeypatch, tmp_path):
    _kb(tmp_path, {f"raw/d{i:03}.md": f"body {i}" for i in range(25)})

    resp = _run(monkeypatch, ["--kb", str(tmp_path), "--limit", "0"])

    missing = resp["data"]["extractions"]["missing"]
    assert missing["count"] == 25 and len(missing["items"]) == 25
    assert missing["truncated"] is False


def test_no_bare_list_survives_anywhere_in_the_payload(monkeypatch, tmp_path):
    """Uniform shape: a reader should not have to remember which lists can be
    truncated and which cannot.

    Stated structurally rather than as a whitelist of today's eleven paths. A
    whitelist cannot fail when a twelfth check adds an unbounded list, which is
    the one regression this test exists to catch -- it would have passed on the
    very payload it is supposed to reject.
    """
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    _article(store, "wiki/c.md", "| `Auth` | bool |\n", ["raw/a.md"])

    data = _run(monkeypatch, ["--kb", str(tmp_path)])["data"]

    def bare_lists(node, path="data"):
        if isinstance(node, dict):
            # A wrapper's own "items" is the shown slice and is meant to be a list.
            inner = {k: v for k, v in node.items()
                     if not (k == "items" and set(node) == {"count", "items",
                                                            "truncated"})}
            for k, v in inner.items():
                yield from bare_lists(v, f"{path}.{k}")
        elif isinstance(node, list):
            yield path

    offenders = list(bare_lists(data))
    assert offenders == [], f"unwrapped list(s) in the payload: {offenders}"


def test_the_payload_records_the_limit_it_was_produced_under(monkeypatch, tmp_path):
    """Without it a reader holding a saved payload cannot tell whether a 20-item
    list was capped at 20 or merely happened to have 20 rows."""
    _kb(tmp_path, {"raw/a.md": "a body"})

    default = _run(monkeypatch, ["--kb", str(tmp_path)])
    assert default["data"]["limit"] == 20

    unlimited = _run(monkeypatch, ["--kb", str(tmp_path), "--limit", "0"])
    assert unlimited["data"]["limit"] == 0


def test_a_path_that_is_not_a_knowledge_base_is_an_error_not_a_clean_bill(
        monkeypatch, tmp_path):
    """In the one command built for diagnosis, a typo'd --kb was indistinguishable
    from a healthy empty KB: 0 match / 0 missing / 0 mismatched and ok: true."""
    resp = _run(monkeypatch, ["--kb", str(tmp_path / "nope")])

    assert resp["ok"] is False
    assert resp["error"]["code"] == "NOT_A_KB"
