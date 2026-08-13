"""Tests for the grounding check: names an article asserts that no source has.

Issue #42. Compiling go-zero produced a `MiddlewaresConf` table with an `Auth`
field the framework does not declare, and a numbered middleware chain that
appeared in no extraction. Both read as authoritative, and at query time the
fabricated prose beat the correct table in 5 of 5 samples. The prompt constraint
in core/merge.py asks the writer not to do it; this is the part that can tell
whether it stopped.

Two properties matter more than breadth here. It must catch the shapes #42
produced -- a table row and an ordered list of named items -- and it must stay
quiet on ordinary prose, because an operator who meets one false positive in a
181-article report stops reading the list.
"""
from __future__ import annotations

from pathlib import Path

from kb_ai.core import grounding
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage import extraction as exl
from kb_ai.storage.store import KBStore, _compute_checksum


def _kb(base: Path, *, extractions: dict[str, ExtractionResult],
        articles: dict[str, str]) -> KBStore:
    """A KB with one raw document plus extraction per entry, and its articles."""
    store = KBStore(str(base))
    for rel, extraction in extractions.items():
        store.write_raw(rel, f"body of {rel}")
        exl.persist(store, rel, extraction,
                    source_checksum=_compute_checksum(store.read_raw(rel)),
                    extract_model="m")
    for rel, content in articles.items():
        store.write_article(rel, content)
    return store


def _article(body: str, sources: list[str] | str = "raw/a.md") -> str:
    if isinstance(sources, str):
        sources = [sources]
    lines = "\n".join(f"  - {s}" for s in sources)
    return f"---\ntitle: \"A\"\ntype: concept\nsources:\n{lines}\n---\n\n{body}\n"


# ── named_items: what the check treats as a claim about a named thing ──

def test_code_spanned_name_in_a_table_row_is_a_candidate():
    """The #42 shape: a config-field table whose first cell names the field."""
    names = dict(grounding.named_items("| `Auth` | bool | enables authentication |\n"))
    assert "Auth" in names


def test_a_code_span_reports_the_name_out_of_a_whole_signature():
    """Articles code-span the whole declaration. Cutting at the first space made
    the reported name `Set(val`, which is in no extraction by construction -- 182
    of 428 findings on the go-zero knowledge base were this one shape."""
    for line, expected in (
            ("| `Set(val bool)` | stores the value |\n", "Set"),
            ("- `CompareAndSwap(old, new bool) bool` swaps it\n", "CompareAndSwap"),
            ("| `func NewServer(c RestConf) *Server` | constructor |\n", "NewServer"),
            ("- `type MiddlewaresConf struct` gates each middleware\n",
             "MiddlewaresConf")):
        assert expected in dict(grounding.named_items(line)), line


def test_an_identifier_shaped_bold_name_is_a_candidate():
    names = dict(grounding.named_items("1. **MaxConns** — caps concurrency\n"))
    assert "MaxConns" in names


def test_a_bold_prose_label_is_not_a_candidate():
    """Bold is how a generated article labels an ordinary bullet, so it cannot be
    read as "this is a name" the way a code span can. Trusting it produced findings
    on `No`, `Note`, `Acquires` and `Ben` -- around 100 of 428."""
    body = (
        "- **No torn reads**: the value is read or written indivisibly.\n"
        "1. **Acquires** the lock by calling `lock.Lock()`.\n"
        "- **Ben Zhou** — approved the budget\n"
        "- **Thread-safe** reads and writes\n"
    )
    assert grounding.named_items(body) == []


def test_a_method_receiver_is_not_the_name():
    """`func (srv *Server) Start() error` is how Go documents a method, and the
    first identifier after the keyword is the receiver variable."""
    for line, expected in (
            ("| `func (srv *Server) Start() error` | runs the server |\n", "Start"),
            ("- `func (s *Server) Stop()` shuts it down\n", "Stop")):
        assert list(dict(grounding.named_items(line))) == [expected], line


def test_a_keyword_spelled_as_a_name_is_still_a_name():
    """Keywords are lowercase in every language this sees, so the skip list is
    matched case-sensitively. Otherwise Go's `map` silences a declared `Map`, and
    `Type`, `Interface` and `Select` go with it."""
    for line, expected in (("| `Map[K, V]` | generic map |\n", "Map"),
                           ("| `type Type struct` | the type of a type |\n", "Type"),
                           ("- `Select(ctx)` picks one\n", "Select")):
        assert list(dict(grounding.named_items(line))) == [expected], line


def test_a_path_in_a_code_span_is_not_a_name():
    """Reporting `usr` for `/usr/local/bin/myservice` is worse than useless: the
    operator cannot even trace it back to what the article said."""
    body = ("- `/usr/local/bin/myservice` is installed\n"
            "- `./myservice` runs it\n"
            "| `core/fs/files.go` | helpers |\n")
    assert grounding.named_items(body) == []


def test_a_code_span_wrapped_in_bold_is_still_a_code_span():
    """Bold around a code span does not stop it being the author marking code, and
    this shape occurs on 81 lines of the go-zero knowledge base."""
    names = dict(grounding.named_items("- **`Err() error`** reports the failure\n"))
    assert "Err" in names


def test_an_abbreviation_is_not_a_candidate():
    """`e.g` and `i.e` satisfy "contains a dot" without being identifiers."""
    body = "- e.g. the server rejects the request\n- i.e. no goroutine is started\n"
    assert grounding.named_items(body) == []


def test_unmarked_identifier_shaped_token_is_a_candidate():
    """An article that writes the field name bare is making the same claim."""
    for line, expected in (("| MaxConns | limits concurrency |\n", "MaxConns"),
                           ("- max_bytes caps the request body\n", "max_bytes"),
                           ("| rest.Config | the server config |\n", "rest.Config")):
        assert expected in dict(grounding.named_items(line)), line


def test_plain_capitalised_word_is_not_a_candidate_unless_marked_up():
    """The false-positive floor. A table whose first column is prose, or a list of
    sentences, must produce nothing -- otherwise every article reports findings.
    This is also the check's main blind spot: a bare `Auth`, with no backticks and
    no internal capital, is indistinguishable from the word "Auth" in a sentence."""
    body = (
        "| Scenario | Behaviour |\n"
        "|---|---|\n"
        "| Request exceeds the limit | the server rejects it |\n"
        "| Shedding is enabled | load is dropped early |\n"
        "\n"
        "- Timeouts are enforced per route\n"
        "1. The engine builds the chain\n"
    )
    assert grounding.named_items(body) == []


def test_table_header_row_yields_nothing():
    names = dict(grounding.named_items("| Field | Type | Description |\n|---|---|---|\n"))
    assert names == {}


def test_wikilinks_are_not_candidates():
    """A [[wikilink]] names another article, not something the source declared."""
    assert grounding.named_items("- [[Rest Engine Core]] covers the chain\n") == []


def test_fenced_code_blocks_are_skipped():
    """A known bound, kept deliberate: quoted code gets reformatted on the way into
    an article, so a name's absence there is weaker evidence than in prose."""
    body = "```yaml\n- MaxConns: 1000\n- Gunzip: true\n```\n"
    assert grounding.named_items(body) == []


def test_numbers_and_units_are_not_candidates():
    assert grounding.named_items("| 1000 | the default |\n- 30s timeout\n") == []


def test_a_row_with_no_content_yields_nothing():
    """Both shapes a table can put here: the separator under the header, and a row
    whose cells are all blank."""
    assert grounding.named_items("|---|:--:|\n|  |  |\n") == []


def test_a_token_with_no_letters_is_not_a_candidate():
    """`--flag` style punctuation and bare operators are not names."""
    assert grounding.named_items("| `-->` | arrow |\n") == []


def test_an_unmarked_token_that_is_not_an_identifier_is_not_a_candidate():
    """The shape rule is applied to the whole token, so a hyphenated word does not
    slip through on the strength of its internal capital."""
    assert grounding.named_items("- Fire-And-Forget delivery is used here\n") == []


def test_a_candidate_is_reported_once_with_its_first_line():
    body = "| `Auth` | bool |\n| `Auth` | again |\n"
    items = grounding.named_items(body)
    assert [n for n, _ in items] == ["Auth"]
    assert items[0][1] == "| `Auth` | bool |"


# ── check_grounding over a knowledge base ──────────────────────────────

def test_flags_a_name_that_appears_in_no_source(tmp_path):
    """The reproduction from #42, reduced: `Auth` is 0 in raw, 0 in the
    extraction, 1 in the wiki."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            summary="MiddlewaresConf declares the middleware switches",
            enumerations=[{"name": "MiddlewaresConf fields", "kind": "struct fields",
                           "ordered": False, "items": ["Shedding", "Timeout"]}])},
        articles={"wiki/concept/c.md": _article(
            "| `Shedding` | bool |\n| `Auth` | bool |\n")})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == ["wiki/concept/c.md"]
    assert [f.name for f in check.unsourced] == ["Auth"]
    assert check.unsourced[0].article == "wiki/concept/c.md"


def test_a_renamed_field_is_flagged(tmp_path):
    """#42's second instance in the same table: the real field `Shedding` was
    written `Shedder`. A prefix match would let this through."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            enumerations=[{"name": "fields", "kind": "struct fields", "ordered": False,
                           "items": ["Shedding"]}])},
        articles={"wiki/c.md": _article("| `Shedder` | bool |\n")})

    check = grounding.check_grounding(str(tmp_path))

    assert [f.name for f in check.unsourced] == ["Shedder"]


def test_a_name_the_extraction_carries_is_not_flagged(tmp_path):
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            concepts=[{"title": "Shedding", "summary": "load shedding switch"}])},
        articles={"wiki/c.md": _article("| `Shedding` | bool |\n")})

    check = grounding.check_grounding(str(tmp_path))

    assert check.unsourced == []


def test_a_name_is_sourced_by_any_payload_field(tmp_path):
    """The haystack is the whole extraction payload, not just enumerations: a
    field named only in a claim is still named in the material."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            claims=[{"claim": "MaxConns defaults to 0", "source": "config.go",
                     "surprising": False}])},
        articles={"wiki/c.md": _article("| `MaxConns` | int |\n")})

    assert grounding.check_grounding(str(tmp_path)).unsourced == []


def test_an_article_may_cite_the_file_it_was_composed_from(tmp_path):
    """The document's own identity is part of the material. Leaving the source path
    out of the haystack reported `rsa.go` on the article compiled from
    raw/go-zero__core__codec__rsa.go.md."""
    _kb(tmp_path,
        extractions={"raw/go-zero__core__codec__rsa.go.md": ExtractionResult(
            summary="RSA encryption helpers")},
        articles={"wiki/c.md": _article(
            "- `rsa.go` declares the encrypter\n",
            sources=["raw/go-zero__core__codec__rsa.go.md"])})

    assert grounding.check_grounding(str(tmp_path)).unsourced == []


def test_a_directory_in_the_source_path_does_not_source_a_name(tmp_path):
    """Only the document's own filename counts, not the directories above it.
    Otherwise an article compiled from .../auth/... has an invented `Auth`
    unconditionally laundered by its own path -- the exact name from #42."""
    _kb(tmp_path,
        extractions={"raw/go-zero__zrpc__internal__auth__credential.go.md":
                     ExtractionResult(summary="credential checking")},
        articles={"wiki/c.md": _article(
            "| `Auth` | bool |\n",
            sources=["raw/go-zero__zrpc__internal__auth__credential.go.md"])})

    assert [f.name for f in grounding.check_grounding(str(tmp_path)).unsourced] == [
        "Auth"]


def test_a_qualified_name_is_sourced_when_every_segment_is(tmp_path):
    """The article writing `syncx.Limit` for a `Limit` the material declares in a
    `syncx` package has invented nothing -- it has been more precise. 12 of the 117
    findings on the go-zero knowledge base were this."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            summary="the syncx package exposes Limit for bounded concurrency")},
        articles={"wiki/c.md": _article("| `syncx.Limit` | struct |\n")})

    assert grounding.check_grounding(str(tmp_path)).unsourced == []


def test_a_qualified_name_whose_tail_is_absent_is_still_flagged(tmp_path):
    """The leniency must not extend to qualifying a fabrication: a package name the
    material happens to mention cannot launder the member."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            summary="the syncx package exposes Limit for bounded concurrency")},
        articles={"wiki/c.md": _article("| `syncx.Auth` | struct |\n")})

    assert [f.name for f in grounding.check_grounding(str(tmp_path)).unsourced] == [
        "syncx.Auth"]


def test_case_difference_alone_is_not_a_finding(tmp_path):
    """Deliberately under-reports. The check makes a strong claim about a name, so
    a name whose letters appear in the material in any casing is not evidence of
    fabrication -- at the cost of missing a `Foo` invented alongside prose about
    "foo"."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(summary="the auth middleware")},
        articles={"wiki/c.md": _article("| `Auth` | bool |\n")})

    assert grounding.check_grounding(str(tmp_path)).unsourced == []


def test_a_bare_name_is_sourced_by_its_qualified_form(tmp_path):
    """An article writes `Config` for what the extraction called `rest.Config`.
    Requiring the qualifier to match too would report the rename shape (#42's
    `Shedder`) and this ordinary abbreviation identically."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(summary="the rest.Config struct")},
        articles={"wiki/c.md": _article("| `Config` | struct |\n")})

    assert grounding.check_grounding(str(tmp_path)).unsourced == []


def test_sources_pool_across_every_extraction_the_article_names(tmp_path):
    """A merged article is composed from several extractions at once, so a name
    from the second one must not read as unsourced."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(summary="engine"),
                     "raw/b.md": ExtractionResult(summary="Gunzip decompresses")},
        articles={"wiki/c.md": _article("| `Gunzip` | bool |\n",
                                        sources=["raw/a.md", "raw/b.md"])})

    assert grounding.check_grounding(str(tmp_path)).unsourced == []


def test_a_comma_joined_sources_entry_is_split(tmp_path):
    """create_new_article is handed ", ".join(rels) as its source_path, and the
    merge-diff path appends that string to sources: verbatim, so one frontmatter
    item can name several documents."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(summary="engine"),
                     "raw/b.md": ExtractionResult(summary="Gunzip decompresses")},
        articles={"wiki/c.md": _article("| `Gunzip` | bool |\n",
                                        sources=["raw/a.md, raw/b.md"])})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == ["wiki/c.md"]
    assert check.unsourced == []


def test_an_article_with_no_frontmatter_is_skipped_with_a_reason(tmp_path):
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult()},
        articles={"wiki/c.md": "# No frontmatter\n\n| `Auth` | bool |\n"})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == []
    assert check.unsourced == []
    assert len(check.skipped) == 1
    assert "frontmatter" in check.skipped[0][1]


def test_an_article_naming_no_sources_is_skipped(tmp_path):
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult()},
        articles={"wiki/c.md": "---\ntitle: \"A\"\n---\n\n| `Auth` | bool |\n"})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == []
    assert "no sources" in check.skipped[0][1]


def test_an_article_whose_extraction_is_missing_is_skipped_not_flagged(tmp_path):
    """Every name would be unsourced against an empty haystack, which is a report
    about the missing extraction (F3's job) and not about the article."""
    _kb(tmp_path, extractions={}, articles={"wiki/c.md": _article("| `Auth` | bool |\n")})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == []
    assert check.unsourced == []
    assert "missing" in check.skipped[0][1]


def test_one_unreadable_source_skips_the_article(tmp_path):
    """Checking against a partial haystack would report the other document's names
    as fabricated."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(summary="engine")},
        articles={"wiki/c.md": _article("| `Gunzip` | bool |\n",
                                        sources=["raw/a.md", "raw/b.md"])})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == []
    assert check.unsourced == []
    assert "raw/b.md" in check.skipped[0][1]


def test_a_source_path_outside_raw_is_reported_as_a_reason(tmp_path):
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult()},
        articles={"wiki/c.md": _article("| `Auth` | bool |\n", sources=["../etc/passwd"])})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == []
    assert check.skipped and check.skipped[0][0] == "wiki/c.md"


def test_frontmatter_that_is_not_a_mapping_is_skipped_with_a_reason(tmp_path):
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult()},
        articles={"wiki/c.md": "---\n- just a list\n---\n\n| `Auth` | bool |\n"})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == []
    assert "not a mapping" in check.skipped[0][1]


def test_frontmatter_that_is_not_valid_yaml_is_skipped_with_a_reason(tmp_path):
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult()},
        articles={"wiki/c.md": "---\ntitle: \"unclosed\nsources: [\n---\n\nbody\n"})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == []
    assert "YAML" in check.skipped[0][1]


def test_an_unreadable_article_is_skipped_rather_than_raising(tmp_path):
    """rglob matches a directory named *.md too, and one bad entry must not end the
    scan -- this is the command an operator reaches for when a KB looks wrong."""
    store = _kb(tmp_path, extractions={"raw/a.md": ExtractionResult(summary="x")},
                articles={"wiki/good.md": _article("prose only\n")})
    (store.wiki_dir / "bad.md").mkdir()

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == ["wiki/good.md"]
    assert check.skipped == [("wiki/bad.md", check.skipped[0][1])]
    assert "unreadable" in check.skipped[0][1]


def test_no_wiki_directory_yields_an_empty_check(tmp_path):
    (tmp_path / "raw").mkdir(parents=True)

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == [] and check.unsourced == [] and check.skipped == []


def test_dotfiles_under_wiki_are_ignored(tmp_path):
    store = _kb(tmp_path, extractions={"raw/a.md": ExtractionResult()}, articles={})
    (store.wiki_dir).mkdir(parents=True, exist_ok=True)
    (store.wiki_dir / ".draft.md").write_text(_article("| `Auth` | bool |\n"))

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == [] and check.skipped == []


def test_frontmatter_values_are_not_scanned_for_candidates(tmp_path):
    """tags: and sources: are scaffolding. A tag list read as a body would report
    every tag whose spelling the extraction happens not to use."""
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult(summary="engine")},
        articles={"wiki/c.md": "---\ntitle: \"A\"\nsources:\n  - raw/a.md\n"
                               "tags:\n  - `MaxConns`\n---\n\nprose only\n"})

    assert grounding.check_grounding(str(tmp_path)).unsourced == []


_REALISTIC_ARTICLE = """## Overview

`RestConf` is the top-level configuration. See [[Rest Engine Core]].

## Fields

| Field | Type | Notes |
|-------|------|-------|
| `Shedding` | bool | load shedding |
| `Timeout` | int | per-route deadline |

## API

| Signature | Effect |
|-----------|--------|
| `Set(val bool)` | stores the value |
| `func NewServer(c RestConf) *Server` | builds the server |

## Semantics

- **No torn reads**: the value is read or written indivisibly.
- **Thread-safe** access via `sync.RWMutex`.
1. **Acquires** the lock, i.e. no goroutine proceeds.
2. **Compute** the new value (`old + val`).
- e.g. a request over `MaxBytes` is rejected.

## Related

- [[Adaptive Load Shedder]]
- [[Rest Server Configuration]]
"""


def test_a_realistically_shaped_article_yields_nothing(tmp_path):
    """The precision regression test. Every name here is in the material, and the
    two mistakes this covers were both invisible to line coverage: reading a code
    span as `Set(val`, and reading a bold prose label as a name. Measured on the
    181-article go-zero knowledge base, those two accounted for roughly 280 of 428
    findings."""
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            summary="RestConf configures the server; sync.RWMutex guards access.",
            concepts=[{"title": "Set", "summary": "stores the value"},
                      {"title": "NewServer", "summary": "builds a Server"}],
            claims=[{"claim": "MaxBytes bounds the request body",
                     "source": "config.go", "surprising": False}],
            enumerations=[{"name": "MiddlewaresConf fields", "kind": "struct fields",
                           "ordered": False, "items": ["Shedding", "Timeout"]}])},
        articles={"wiki/c.md": _article(_REALISTIC_ARTICLE)})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == ["wiki/c.md"]
    assert [(f.name, f.line) for f in check.unsourced] == []


def test_a_fabrication_inside_a_realistically_shaped_article_is_still_found(tmp_path):
    """The other half of the pair: the precision fixes must not buy silence."""
    body = _REALISTIC_ARTICLE.replace(
        "| `Timeout` | int | per-route deadline |",
        "| `Timeout` | int | per-route deadline |\n| `Auth` | bool | JWT |")
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(
            summary="RestConf configures the server; sync.RWMutex guards access.",
            concepts=[{"title": "Set", "summary": "stores the value"},
                      {"title": "NewServer", "summary": "builds a Server"}],
            claims=[{"claim": "MaxBytes bounds the request body",
                     "source": "config.go", "surprising": False}],
            enumerations=[{"name": "MiddlewaresConf fields", "kind": "struct fields",
                           "ordered": False, "items": ["Shedding", "Timeout"]}])},
        articles={"wiki/c.md": _article(body)})

    assert [f.name for f in grounding.check_grounding(str(tmp_path)).unsourced] == ["Auth"]


def test_summary_reports_names_articles_and_skips(tmp_path):
    _kb(tmp_path,
        extractions={"raw/a.md": ExtractionResult(summary="Shedding")},
        articles={"wiki/one.md": _article("| `Auth` | bool |\n| `Shedder` | bool |\n"),
                  "wiki/two.md": _article("| `Shedding` | bool |\n"),
                  "wiki/three.md": "no frontmatter\n"})

    check = grounding.check_grounding(str(tmp_path))

    assert check.checked == ["wiki/one.md", "wiki/two.md"]
    assert check.flagged == ["wiki/one.md"]
    summary = check.summary()
    assert "2 unsourced" in summary
    assert "1 of 2" in summary
    assert "1 skipped" in summary


def test_summary_of_a_run_that_could_check_nothing_does_not_read_as_clean(tmp_path):
    """A knowledge base extracted before schema_version 2 skips every article, and
    "0 unsourced names" is exactly the wrong first phrase to hand an operator for
    a run that looked at nothing."""
    _kb(tmp_path, extractions={}, articles={"wiki/c.md": _article("| `Auth` | bool |\n")})

    summary = grounding.check_grounding(str(tmp_path)).summary()

    assert summary == "no articles could be checked (1 skipped)"


def test_summary_of_a_knowledge_base_with_no_articles_at_all(tmp_path):
    (tmp_path / "wiki").mkdir(parents=True)

    assert grounding.check_grounding(str(tmp_path)).summary() == "no articles"


def test_summary_of_a_clean_knowledge_base(tmp_path):
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult(summary="Shedding")},
        articles={"wiki/c.md": _article("| `Shedding` | bool |\n")})

    assert grounding.check_grounding(str(tmp_path)).summary() == (
        "0 unsourced names in 0 of 1 articles (0 skipped)")


def test_check_grounding_never_writes(tmp_path):
    """Same contract as F3 and F5: safe to point at a read-only KB, or someone
    else's."""
    _kb(tmp_path, extractions={"raw/a.md": ExtractionResult(summary="Shedding")},
        articles={"wiki/c.md": _article("| `Auth` | bool |\n")})
    before = {p: p.stat().st_mtime_ns for p in sorted(tmp_path.rglob("*")) if p.is_file()}

    grounding.check_grounding(str(tmp_path))

    after = {p: p.stat().st_mtime_ns for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    assert after == before
