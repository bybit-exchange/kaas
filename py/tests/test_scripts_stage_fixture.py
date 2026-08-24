"""Tests for the staged fixture builder (spec FX1, FX2).

FX2 exists because compiling all 38 fixture documents in one run routes every
version chain into a single `merge→create` call, which is the one write path A1 was
always going to get right. Staging one version per run is what puts the merge paths
under test at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kb_ai.storage.store import KBStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import stage_fixture as sf  # noqa: E402


def case(chain, shape="A", title="Plan"):
    return {"shape": shape, "title": title, "chain": chain, "n": len(chain)}


# ── stages ──────────────────────────────────────────────────────────

def test_each_stage_takes_one_version_of_every_chain():
    stages = sf.stages([case(["raw/a1.md", "raw/a2.md"]),
                        case(["raw/b1.md", "raw/b2.md"])])

    assert stages == [["raw/a1.md", "raw/b1.md"], ["raw/a2.md", "raw/b2.md"]]


def test_a_longer_chain_keeps_going_after_the_short_ones_run_out():
    """P4's four-version chain has to merge repeatedly into an article that earlier
    versions already wrote, which is the case the single-run fixture never reached.
    """
    stages = sf.stages([case(["raw/a1.md", "raw/a2.md"]),
                        case(["raw/p1.md", "raw/p2.md", "raw/p3.md", "raw/p4.md"])])

    assert stages == [["raw/a1.md", "raw/p1.md"], ["raw/a2.md", "raw/p2.md"],
                      ["raw/p3.md"], ["raw/p4.md"]]


def test_a_document_in_two_chains_is_staged_once():
    """A document can be both the later version of one chain and the earlier of
    another, and staging it twice would compile it twice in one stage.
    """
    stages = sf.stages([case(["raw/a.md", "raw/b.md"]),
                        case(["raw/b.md", "raw/c.md"], shape="B")])

    assert stages == [["raw/a.md", "raw/b.md"], ["raw/c.md"]]


def test_no_cases_is_no_stages():
    assert sf.stages([]) == []


def test_stage_members_come_back_in_path_order():
    stages = sf.stages([case(["raw/z.md", "raw/y.md"]), case(["raw/a.md", "raw/b.md"])])

    assert stages[0] == ["raw/a.md", "raw/z.md"]


# ── materialising a stage ───────────────────────────────────────────

@pytest.fixture
def source(tmp_path) -> KBStore:
    store = KBStore(str(tmp_path / "src"))
    for name in ("a1", "a2"):
        store.write_raw(f"raw/{name}.md", f"---\ntitle: {name}\n---\n\nbody of {name}\n")
        extraction = store.base_dir / "extraction" / f"{name}.md"
        extraction.parent.mkdir(parents=True, exist_ok=True)
        extraction.write_text(f"---\nsource: raw/{name}.md\n---\n\n## Claims\n")
    (store.base_dir / "kaas.json").write_text('{"categories": ["concept"]}')
    return store


def test_materialising_copies_the_documents_and_their_extractions(source, tmp_path):
    work = tmp_path / "work"

    sf.materialize(source.base_dir, work, ["raw/a1.md"])

    assert (work / "raw/a1.md").read_text() == (source.base_dir / "raw/a1.md").read_text()
    assert (work / "extraction/a1.md").exists()
    assert not (work / "raw/a2.md").exists()


def test_the_category_config_rides_along_so_the_first_compile_does_not_invent_one(
        source, tmp_path):
    """A KB with no `kaas.json` freezes DEFAULT_CATEGORIES on its first compile, so
    a fixture that lost the file would classify into a different category set than
    the corpus it came from and no chain would land where the case says.
    """
    work = tmp_path / "work"

    sf.materialize(source.base_dir, work, ["raw/a1.md"])

    assert (work / "kaas.json").read_text() == '{"categories": ["concept"]}'


def test_a_later_stage_adds_to_what_the_earlier_one_left(source, tmp_path):
    """The wiki has to survive between stages — that is the whole point of staging.
    Stage N compiles into the articles stage N−1 wrote.
    """
    work = tmp_path / "work"
    sf.materialize(source.base_dir, work, ["raw/a1.md"])
    (work / "wiki").mkdir()
    (work / "wiki" / "article.md").write_text("written by stage 1\n")

    sf.materialize(source.base_dir, work, ["raw/a2.md"])

    assert (work / "raw/a1.md").exists() and (work / "raw/a2.md").exists()
    assert (work / "wiki" / "article.md").read_text() == "written by stage 1\n"


def test_a_document_with_no_extraction_is_copied_anyway(source, tmp_path):
    """14 corpus documents have no cached extraction. They cost an extract call
    rather than being skipped: leaving them out would change which documents a
    chain's article was composed from.
    """
    source.write_raw("raw/fresh.md", "---\ntitle: fresh\n---\n\nbody\n")
    work = tmp_path / "work"

    sf.materialize(source.base_dir, work, ["raw/fresh.md"])

    assert (work / "raw/fresh.md").exists()
    assert not (work / "extraction/fresh.md").exists()


def test_a_missing_document_is_reported_rather_than_silently_skipped(source, tmp_path):
    with pytest.raises(FileNotFoundError, match="raw/gone.md"):
        sf.materialize(source.base_dir, tmp_path / "work", ["raw/gone.md"])


# ── the plan ────────────────────────────────────────────────────────

def test_the_plan_names_one_compile_per_stage(tmp_path):
    lines = sf.plan([["raw/a1.md"], ["raw/a2.md"]], tmp_path / "work")

    assert len(lines) == 2
    assert "stage 1" in lines[0] and "1 document" in lines[0]
    assert str(tmp_path / "work") in lines[0]


# ── the command line ────────────────────────────────────────────────

def _cases_file(tmp_path, chains):
    import json
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([case(c) for c in chains]))
    return path


def test_main_without_a_stage_writes_nothing(source, tmp_path, capsys):
    cases = _cases_file(tmp_path, [["raw/a1.md", "raw/a2.md"]])
    work = tmp_path / "work"

    assert sf.main(["--kb", str(source.base_dir), "--cases", str(cases),
                    "--out", str(work)]) == 0

    assert not work.exists()
    assert "nothing written" in capsys.readouterr().err


def test_main_materialises_the_named_stage(source, tmp_path):
    cases = _cases_file(tmp_path, [["raw/a1.md", "raw/a2.md"]])
    work = tmp_path / "work"

    assert sf.main(["--kb", str(source.base_dir), "--cases", str(cases),
                    "--out", str(work), "--stage", "2"]) == 0

    assert (work / "raw/a2.md").exists()
    assert not (work / "raw/a1.md").exists()


def test_main_refuses_a_stage_that_does_not_exist(source, tmp_path, capsys):
    cases = _cases_file(tmp_path, [["raw/a1.md", "raw/a2.md"]])

    code = sf.main(["--kb", str(source.base_dir), "--cases", str(cases),
                    "--out", str(tmp_path / "work"), "--stage", "3"])

    assert code == 1
    assert "outside 1..2" in capsys.readouterr().err
