"""Tests for the kb-ai derive CLI: payload shape, error codes, volume gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._errors import SlugExistsError
from kb_ai.commands import derive as derive_cmd
from kb_ai.derive._types import DeriveReport, DocumentRef, Skipped


def _report(**over) -> DeriveReport:
    base = DeriveReport(
        derived_kb="/kb/derived/pricing", slug="pricing", topic="pricing",
        selected_articles=["wiki/a.md"],
        skipped_articles=[Skipped(ref="wiki/b.md", reason="no_sources_key")],
        documents=[DocumentRef(rel_path="raw/a.md", checksum="a" * 16, size_bytes=2048)],
        filter_batches=2, offtopic_articles=["wiki/c.md"], compiled=True,
        compile={"compiled": 1, "cost": {"total_cost_usd": 0.5}},
        cost={"total_cost_usd": 0.75},
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def _run(monkeypatch, argv, *, derive=None):
    out: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: out.append(str(a[0])) if a else None)
    if derive is not None:
        monkeypatch.setattr(derive_cmd, "derive_kb", derive)
    derive_cmd.run_derive(argv)
    return json.loads(out[-1])


def test_defaults_kb_to_dot_kaas():
    args = derive_cmd.build_parser().parse_args(["pricing"])
    assert args.kb == "./.kaas"
    assert args.slug is None and args.force is False and args.yes is False
    assert args.prune is False


def test_prune_is_off_unless_asked_for(monkeypatch):
    """The PRECISION pass ships off; --prune is the only way to reach it."""
    seen: dict = {}

    def fake_derive(source_kb, topic, **kw):
        seen.update(kw)
        return _report()

    _run(monkeypatch, ["pricing", "--kb", "/kb", "--yes"], derive=fake_derive)
    assert seen["prune"] is False

    _run(monkeypatch, ["pricing", "--kb", "/kb", "--yes", "--prune"], derive=fake_derive)
    assert seen["prune"] is True


def test_success_payload(monkeypatch):
    seen: dict = {}

    def fake_derive(source_kb, topic, **kw):
        seen.update({"source_kb": source_kb, "topic": topic, **kw})
        return _report()

    resp = _run(monkeypatch, ["pricing", "--kb", "/kb", "--yes"], derive=fake_derive)

    assert resp["ok"] is True
    data = resp["data"]
    assert data["derived_kb"] == "/kb/derived/pricing"
    assert data["slug"] == "pricing"
    assert data["topic"] == "pricing"
    assert data["selected"] == 1
    assert data["skipped"] == [{"ref": "wiki/b.md", "reason": "no_sources_key"}]
    assert data["documents"] == 1
    assert data["bytes"] == 2048
    assert data["offtopic"] == 1
    assert data["filter_batches"] == 2
    assert data["compiled"] is True
    assert data["compile"] == {"compiled": 1, "cost": {"total_cost_usd": 0.5}}
    assert data["cost"] == {"total_cost_usd": 0.75}
    assert "KAAS_KB_DIR=/kb/derived/pricing" in data["next"]
    assert seen["source_kb"] == "/kb"
    assert seen["approve"] is None  # --yes auto-approves


def test_failure_payload_carries_the_error_code(monkeypatch):
    def boom(*a, **kw):
        raise SlugExistsError("/kb/derived/pricing already exists; pass --force")

    resp = _run(monkeypatch, ["pricing", "--yes"], derive=boom)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "SLUG_EXISTS"
    assert "--force" in resp["error"]["message"]


def test_unexpected_error_is_not_swallowed(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("disk on fire")

    with pytest.raises(RuntimeError):
        _run(monkeypatch, ["pricing", "--yes"], derive=boom)


def test_gate_declines_without_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(derive_cmd.sys.stdin, "isatty", lambda: False, raising=False)
    approve = derive_cmd._make_approve(derive_cmd.build_parser().parse_args(["pricing"]))
    assert approve is not None
    assert approve(_report(compiled=False)) is False


def test_gate_accepts_a_yes_on_a_tty(monkeypatch):
    monkeypatch.setattr(derive_cmd.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    approve = derive_cmd._make_approve(derive_cmd.build_parser().parse_args(["pricing"]))
    assert approve(_report(compiled=False)) is True


def test_gate_rejects_anything_else_on_a_tty(monkeypatch):
    monkeypatch.setattr(derive_cmd.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    approve = derive_cmd._make_approve(derive_cmd.build_parser().parse_args(["pricing"]))
    assert approve(_report(compiled=False)) is False


def test_declined_run_reports_ok_with_compiled_false(monkeypatch):
    resp = _run(monkeypatch, ["pricing", "--yes"],
                derive=lambda *a, **kw: _report(compiled=False, compile=None,
                                                offtopic_articles=[], cost=None))
    assert resp["ok"] is True
    assert resp["data"]["compiled"] is False
    assert "--force" in resp["data"]["next"]


def test_declined_run_guidance_does_not_promise_a_resume(monkeypatch):
    """--force re-runs the filter and re-copies the documents; only the source KB's
    extraction layer is reused. Promising a cheap resume sends the operator into a
    second full-price run they were told they had already paid for.
    """
    resp = _run(monkeypatch, ["pricing", "--yes"],
                derive=lambda *a, **kw: _report(compiled=False, compile=None,
                                                offtopic_articles=[], cost=None))
    guidance = resp["data"]["next"]
    assert "without re-resolving documents" not in guidance
    assert "filter runs again" in guidance
    assert "extraction layer is reused" in guidance


# ── --select-from ────────────────────────────────────────────────────

def test_select_from_defaults_to_articles():
    args = derive_cmd.build_parser().parse_args(["pricing"])
    assert args.select_from == "articles"


def test_select_from_documents_reaches_derive_kb(monkeypatch):
    seen: dict = {}

    def fake_derive(source_kb, topic, **kw):
        seen.update(kw)
        return _report()

    _run(monkeypatch, ["pricing", "--kb", "/kb", "--yes",
                       "--select-from", "documents"], derive=fake_derive)
    assert seen["select_from"] == "documents"


def test_select_from_rejects_an_unknown_value():
    with pytest.raises(SystemExit):
        derive_cmd.build_parser().parse_args(["pricing", "--select-from", "everything"])


def test_gate_counts_documents_in_documents_mode(monkeypatch, capsys):
    """selected_articles is empty by design under --select-from documents, so a
    gate that only reports articles would tell the user nothing matched."""
    monkeypatch.setattr(derive_cmd.sys.stdin, "isatty", lambda: False, raising=False)
    args = derive_cmd.build_parser().parse_args(
        ["pricing", "--select-from", "documents"])
    report = _report(compiled=False)
    report.selected_articles = []
    report.selected_documents = ["raw/a.md", "raw/b.md"]

    derive_cmd._make_approve(args)(report)

    assert "2 documents matched" in capsys.readouterr().err
