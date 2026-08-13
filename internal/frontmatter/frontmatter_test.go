package frontmatter

import (
	"strings"
	"testing"
)

func TestExtractTitle_WithFrontmatterTitle(t *testing.T) {
	content := []byte("---\ntitle: My Document\ndate: 2024-01-01\n---\n# Heading\nBody text")
	got := ExtractTitle(content)
	if got != "My Document" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "My Document")
	}
}

func TestExtractTitle_QuotedTitle_Double(t *testing.T) {
	content := []byte("---\ntitle: \"Quoted Title\"\n---\nBody")
	got := ExtractTitle(content)
	if got != "Quoted Title" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Quoted Title")
	}
}

func TestExtractTitle_QuotedTitle_Single(t *testing.T) {
	content := []byte("---\ntitle: 'Single Quoted'\n---\nBody")
	got := ExtractTitle(content)
	if got != "Single Quoted" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Single Quoted")
	}
}

func TestExtractTitle_NoTitle_FallbackH1(t *testing.T) {
	content := []byte("---\ndate: 2024-01-01\nauthor: test\n---\n# Fallback Heading\nBody")
	got := ExtractTitle(content)
	if got != "Fallback Heading" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Fallback Heading")
	}
}

func TestExtractTitle_NoFrontmatter_FallbackH1(t *testing.T) {
	content := []byte("# Just a Heading\n\nSome body text here.")
	got := ExtractTitle(content)
	if got != "Just a Heading" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Just a Heading")
	}
}

func TestExtractTitle_Empty(t *testing.T) {
	got := ExtractTitle([]byte{})
	if got != "" {
		t.Errorf("ExtractTitle(empty) = %q, want %q", got, "")
	}
}

func TestExtractTitle_Nil(t *testing.T) {
	got := ExtractTitle(nil)
	if got != "" {
		t.Errorf("ExtractTitle(nil) = %q, want %q", got, "")
	}
}

func TestExtractTitle_NoFrontmatterNoH1(t *testing.T) {
	content := []byte("Just plain text without any headings or frontmatter.")
	got := ExtractTitle(content)
	if got != "" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "")
	}
}

func TestExtractTitle_MalformedFrontmatter(t *testing.T) {
	// Unclosed frontmatter block — should not crash, return fallback
	content := []byte("---\ntitle: Orphan\ndate: 2024-01-01\n\n# Real Heading\nBody")
	got := ExtractTitle(content)
	if got != "Real Heading" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Real Heading")
	}
}

func TestExtractTitle_WithBOM(t *testing.T) {
	// UTF-8 BOM + valid frontmatter
	content := []byte("\xef\xbb\xbf---\ntitle: BOM Title\n---\nBody")
	got := ExtractTitle(content)
	if got != "BOM Title" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "BOM Title")
	}
}

func TestExtractTitle_BOM_NoFrontmatter_H1(t *testing.T) {
	content := []byte("\xef\xbb\xbf# BOM Heading\nBody text")
	got := ExtractTitle(content)
	if got != "BOM Heading" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "BOM Heading")
	}
}

func TestExtractTitle_TitleWithSpaceBeforeColon(t *testing.T) {
	content := []byte("---\ntitle : Spaced Colon\n---\nBody")
	got := ExtractTitle(content)
	if got != "Spaced Colon" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Spaced Colon")
	}
}

func TestExtractTitle_TitleIsFirstKeyInFrontmatter(t *testing.T) {
	content := []byte("---\ntitle: First Key\nauthor: test\n---\nBody")
	got := ExtractTitle(content)
	if got != "First Key" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "First Key")
	}
}

func TestExtractTitle_CRLFLineEndings(t *testing.T) {
	content := []byte("---\r\ntitle: CRLF Title\r\ndate: 2024\r\n---\r\nBody")
	got := ExtractTitle(content)
	if got != "CRLF Title" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "CRLF Title")
	}
}

func TestExtractTitle_H1NotFirst(t *testing.T) {
	// H1 is not on the first line, but should still be found
	content := []byte("Some intro text.\n\n# Late Heading\nBody")
	got := ExtractTitle(content)
	if got != "Late Heading" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Late Heading")
	}
}

func TestExtractTitle_H2NotMatched(t *testing.T) {
	// H2 should NOT be used as fallback
	content := []byte("## H2 Only\nBody text")
	got := ExtractTitle(content)
	if got != "" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "")
	}
}

func TestExtractTitle_EmptyTitle(t *testing.T) {
	// title: with empty value — should return "" and fallback to H1
	content := []byte("---\ntitle:\ndate: 2024\n---\n# Fallback\nBody")
	got := ExtractTitle(content)
	if got != "Fallback" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "Fallback")
	}
}

func TestExtractTitle_ChineseTitle(t *testing.T) {
	content := []byte("---\ntitle: 中文标题测试\n---\n正文内容")
	got := ExtractTitle(content)
	if got != "中文标题测试" {
		t.Errorf("ExtractTitle() = %q, want %q", got, "中文标题测试")
	}
}

// --- MayHaveDate / WithDate: stamping an ingest date the write phase can read ---
//
// Block detection here mirrors Python's split_frontmatter (py/src/kb_ai/
// _frontmatter.py), because that is the reader these bytes are written for: the
// opening delimiter is matched on a full strip, the closing one on a right strip
// only, so an indented `---` closes nothing.

func TestMayHaveDate_TrueForADateInALeadingBlock(t *testing.T) {
	if !MayHaveDate([]byte("---\ntitle: One\ndate: 2026-06-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false, want true")
	}
}

func TestMayHaveDate_ToleratesASpaceBeforeTheColon(t *testing.T) {
	// Mirrors what extractFromFrontmatter already accepts for title.
	if !MayHaveDate([]byte("---\ndate : 2026-06-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false, want true")
	}
}

func TestMayHaveDate_FalseWhenTheDateIsInTheBody(t *testing.T) {
	if MayHaveDate([]byte("---\ntitle: One\n---\n\ndate: 2026-06-01\n")) {
		t.Error("MayHaveDate() = true for a body line, want false")
	}
}

func TestMayHaveDate_FalseWithoutABlock(t *testing.T) {
	if MayHaveDate([]byte("# Heading\n\ndate: 2026-06-01\n")) {
		t.Error("MayHaveDate() = true, want false")
	}
}

func TestMayHaveDate_FalseOnAnUnclosedBlock(t *testing.T) {
	if MayHaveDate([]byte("---\ndate: 2026-06-01\n\nbody\n")) {
		t.Error("MayHaveDate() = true for an unclosed block, want false")
	}
}

func TestMayHaveDate_FalseOnAnEmptyDeclaration(t *testing.T) {
	// `date:` with nothing after it is not a date; the caller must stamp one.
	if MayHaveDate([]byte("---\ndate:\ntitle: One\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = true for an empty date, want false")
	}
}

func TestWithDate_PrependsABlockWhenThereIsNone(t *testing.T) {
	got := string(WithDate([]byte("# Heading\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n# Heading\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_PrependedBlockCarriesExtraFields(t *testing.T) {
	got := string(WithDate([]byte("body\n"), "2026-06-01",
		Field{"source", "paste"}, Field{"title", "Q3: the \"plan\""}))
	// Values are double-quoted, so a colon or a quote in a title cannot break the
	// block. Parity fixture: py/tests/test_frontmatter.py asserts PyYAML reads
	// this exact block back.
	want := "---\ndate: 2026-06-01\nsource: \"paste\"\ntitle: \"Q3: the \\\"plan\\\"\"\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_SkipsEmptyExtraFields(t *testing.T) {
	got := string(WithDate([]byte("body\n"), "2026-06-01",
		Field{"source", "paste"}, Field{"title", ""}))
	want := "---\ndate: 2026-06-01\nsource: \"paste\"\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_InsertsIntoAnExistingBlockRatherThanStackingOne(t *testing.T) {
	// A second block above the document's own would leave the document's keys in
	// the body, where the catalog reads them as prose.
	got := string(WithDate([]byte("---\ntitle: One\n---\n\nbody\n"), "2026-06-01",
		Field{"source", "paste"}))
	want := "---\ndate: 2026-06-01\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_ReplacesAnExistingDateLine(t *testing.T) {
	// Inserting instead would leave a duplicate key, and PyYAML takes the last
	// one -- the document's, not the caller's.
	got := string(WithDate([]byte("---\ndate: 2020-01-01\ntitle: One\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\ndate: 2026-06-01\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_ReplacesADateDeclaredWithoutAValue(t *testing.T) {
	got := string(WithDate([]byte("---\ndate:\ntitle: One\n---\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_KeepsCRLFWhenInsertingIntoABlock(t *testing.T) {
	got := string(WithDate([]byte("---\r\ntitle: One\r\n---\r\n\r\nbody\r\n"), "2026-06-01"))
	want := "---\r\ndate: 2026-06-01\r\ntitle: One\r\n---\r\n\r\nbody\r\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_TreatsAnUnclosedBlockAsNoBlock(t *testing.T) {
	// split_frontmatter returns None here, so the document has no frontmatter as
	// far as the reader is concerned and a fresh block goes on top.
	got := string(WithDate([]byte("---\ntitle: One\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n---\ntitle: One\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_AnIndentedClosingDelimiterDoesNotCloseTheBlock(t *testing.T) {
	got := string(WithDate([]byte("---\ntitle: One\n  ---\n\nbody\n"), "2026-06-01"))
	if !strings.HasPrefix(got, "---\ndate: 2026-06-01\n---\n\n---\ntitle: One\n") {
		t.Errorf("WithDate() = %q, want a fresh block on top", got)
	}
}

func TestWithDate_EmptyContentGetsABlock(t *testing.T) {
	got := string(WithDate(nil, "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

// --- the block's own shape: indentation, nesting, provenance comments ---

func TestWithDate_MatchesTheIndentationOfAnIndentedBlock(t *testing.T) {
	// A mapping indented as a whole is valid YAML. Inserting at column 0 would
	// mix indentation levels and PyYAML reads the whole block as nothing -- the
	// document's own labels lost along with the date just written.
	got := string(WithDate([]byte("---\n  title: The Plan\n  author: bob\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\n  date: 2026-06-01\n  title: The Plan\n  author: bob\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_FindsADateInAnIndentedBlock(t *testing.T) {
	if !MayHaveDate([]byte("---\n  title: One\n  date: 2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false, want true")
	}
}

func TestWithDate_ReplacesAnIndentedDateLine(t *testing.T) {
	got := string(WithDate([]byte("---\n  date: 2020-01-01\n  title: One\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\n  date: 2026-06-01\n  title: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_FalseForANestedDateKey(t *testing.T) {
	// meta.date is not the document's date, and treating it as one leaves the
	// document undated with nothing saying so.
	if MayHaveDate([]byte("---\nmeta:\n  author: bob\n  date: 2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = true for a nested key, want false")
	}
}

func TestWithDate_LeavesANestedDateKeyAlone(t *testing.T) {
	got := string(WithDate([]byte("---\nmeta:\n  author: bob\n  date: 2020-01-01\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\ndate: 2026-06-01\nmeta:\n  author: bob\n  date: 2020-01-01\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_LeavesADateInsideALiteralScalarAlone(t *testing.T) {
	// Rewriting a line inside a block scalar would edit the document's prose.
	content := "---\nnotes: |\n  line one\n  date: not a key\n---\n\nbody\n"
	got := string(WithDate([]byte(content), "2026-06-01"))
	want := "---\ndate: 2026-06-01\nnotes: |\n  line one\n  date: not a key\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_ReplacesAQuotedDateKey(t *testing.T) {
	// YAML resolves `"date"` to the same key as `date`, so inserting our own
	// would leave a duplicate that PyYAML settles in the document's favour --
	// silently dropping the date the caller asked for.
	got := string(WithDate([]byte("---\n\"date\": 2020-01-01\ntitle: One\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\ndate: 2026-06-01\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_LooksBehindAProvenanceComment(t *testing.T) {
	// distill prepends "<!-- source: ... -->" to what it ingests, and the reader
	// skips it. Not skipping it here read the document as having no frontmatter,
	// so its authored date was shadowed by the ingest clock.
	if !MayHaveDate([]byte("<!-- source: /tmp/a.md -->\n\n---\ntitle: One\ndate: 2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false behind a provenance comment, want true")
	}
}

func TestWithDate_InsertsBehindAProvenanceComment(t *testing.T) {
	got := string(WithDate([]byte("<!-- source: /tmp/a.md -->\n\n---\ntitle: One\n---\n\nbody\n"),
		"2026-06-01"))
	want := "<!-- source: /tmp/a.md -->\n\n---\ndate: 2026-06-01\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_PrependsWhenAProvenanceCommentHidesNoBlock(t *testing.T) {
	content := "<!-- source: /tmp/a.md -->\n\njust prose\n"
	got := string(WithDate([]byte(content), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n" + content
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

// --- shapes the textual scan must not misread (post-review hardening) ---

func TestMayHaveDate_TrueWhenAYAMLCommentPrecedesTheKeys(t *testing.T) {
	// The block's own level is the level its *keys* sit at. Taking it from a
	// comment instead read this document as undated and then inserted a second
	// date at the comment's indentation, which PyYAML rejects outright: a
	// document that arrived labelled and dated came back {}.
	if !MayHaveDate([]byte("---\n  # written by hand\ndate: 2020-01-01\ntitle: One\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false behind a YAML comment, want true")
	}
}

func TestWithDate_InsertsAtTheKeyIndentationNotACommentsOwn(t *testing.T) {
	got := string(WithDate([]byte("---\n  # written by hand\ntitle: One\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\ndate: 2026-06-01\n  # written by hand\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_TrueForAFlowMapping(t *testing.T) {
	// `{date: ...}` is a mapping PyYAML reads and this scan cannot. Reporting it
	// as undated let the ingest clock be stamped over an authored date -- the one
	// thing the precedence rule exists to prevent -- so an unreadable block
	// counts as possibly dated.
	if !MayHaveDate([]byte("---\n{date: 2020-01-01, title: One}\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false for a flow mapping, want true")
	}
}

func TestMayHaveDate_TrueForASequenceBlock(t *testing.T) {
	if !MayHaveDate([]byte("---\n- a\n- b\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false for a sequence block, want true")
	}
}

func TestWithDate_StacksABlockRatherThanBreakingAnUnreadableOne(t *testing.T) {
	// Only reached when the caller supplied a date explicitly, which outranks the
	// document's own. Inserting a block key above a flow mapping is invalid YAML
	// and costs the document every label it had; stacking keeps all of its bytes
	// and parses.
	got := string(WithDate([]byte("---\n{date: 2020-01-01, title: One}\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n---\n{date: 2020-01-01, title: One}\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_LooksPastAByteOrderMark(t *testing.T) {
	// ExtractTitle already strips the BOM a Windows editor leaves; the block scan
	// did not, so a BOM'd document read as having no frontmatter and had the
	// ingest clock stamped over its authored date.
	if !MayHaveDate([]byte("\xef\xbb\xbf---\ntitle: The Plan\ndate: 2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false past a BOM, want true")
	}
}

func TestWithDate_InsertsPastAByteOrderMarkKeepingIt(t *testing.T) {
	got := string(WithDate([]byte("\xef\xbb\xbf---\ntitle: The Plan\n---\n\nbody\n"), "2026-06-01"))
	want := "\xef\xbb\xbf---\ndate: 2026-06-01\ntitle: The Plan\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_ReplacesTheLastOfDuplicateDateLines(t *testing.T) {
	// PyYAML resolves a duplicate key to the last occurrence, so rewriting the
	// first one leaves the document's date standing and drops the caller's.
	got := string(WithDate([]byte("---\ndate: 2020-01-01\ntitle: One\ndate: 2019-01-01\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\ndate: 2020-01-01\ntitle: One\ndate: 2026-06-01\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_TrueWithoutASpaceAfterTheColon(t *testing.T) {
	// `date:2020-01-01` is not a mapping entry -- YAML needs the space -- so
	// PyYAML reads no mapping at all here. Unreadable, so possibly dated.
	//
	// This assertion alone does not catch the defect: the old scan also returned
	// true here, by reading the line as a dated key. What the space rule actually
	// prevents is a date written *into* such a block, which is pinned by
	// TestWithDate_StacksOverABlockWhoseKeyLacksTheSpaceYAMLNeeds.
	if !MayHaveDate([]byte("---\ndate:2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false, want true for an unreadable block")
	}
}

func TestMayHaveDate_ClosesOnADelimiterWithANonBreakingSpace(t *testing.T) {
	// The reader closes the block with str.rstrip(), which removes every
	// character str.isspace() accepts -- U+00A0 among them. A narrower cutset
	// here saw no block, stacked a second one, and shadowed the authored date.
	if !MayHaveDate([]byte("---\ndate: 2020-01-01\n---\u00a0\n\nbody\n")) {
		t.Error("MayHaveDate() = false for a delimiter closed with U+00A0, want true")
	}
}

func TestMayHaveDate_TrueForATabIndentedBlock(t *testing.T) {
	// YAML forbids a tab as indentation, so this block is not a mapping to the
	// reader at all.
	//
	// As above, this assertion passes under the old scan too -- it found a dated
	// key at the tab's own level. The loss it describes is pinned by
	// TestWithDate_StacksABlockOverTabIndentedFrontmatter.
	if !MayHaveDate([]byte("---\n\tdate: 2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false for a tab-indented block, want true")
	}
}

func TestWithDate_StacksABlockOverTabIndentedFrontmatter(t *testing.T) {
	got := string(WithDate([]byte("---\n\ttitle: One\n---\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n---\n\ttitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_StacksOverABlockWhoseKeyLacksTheSpaceYAMLNeeds(t *testing.T) {
	// `title:One` is a plain scalar, not a mapping entry, so this block is not a
	// mapping to the reader at all. Inserting a date beside it produced a block
	// PyYAML reads as nothing, and the date went with it: the whole point of
	// treating the block as unreadable is that the date has to land somewhere the
	// reader will actually see it.
	got := string(WithDate([]byte("---\ntitle:One\n---\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n---\ntitle:One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_StacksOverASequenceOfMappings(t *testing.T) {
	// "- date: 2020-01-01" has a colon and a space after it, so it reads as a key
	// unless sequence entries are ruled out first -- and the block is a sequence,
	// which the reader resolves to no mapping at all. A date inserted beside it
	// would go where nothing can read it.
	got := string(WithDate([]byte("---\n- date: 2020-01-01\n---\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n---\n- date: 2020-01-01\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

// --- a date whose value is not on the date line ---

func TestMayHaveDate_TrueForADateWhoseValueIsAMapping(t *testing.T) {
	// "date:" alone reads as declared-but-empty only if you stop at that line. A
	// more-indented line below it is the value, and rewriting the key orphaned it:
	// the reader went from a date and a title to nothing at all.
	if !MayHaveDate([]byte("---\ndate:\n  start: 2020-01-01\n  end: 2020-06-01\ntitle: The Plan\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false for a structured date, want true")
	}
}

func TestWithDate_StacksOverADateWhoseValueIsAMapping(t *testing.T) {
	content := "---\ndate:\n  start: 2020-01-01\ntitle: The Plan\n---\n\nbody\n"
	got := string(WithDate([]byte(content), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n" + content
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_TrueForADateWhoseValueIsASequence(t *testing.T) {
	if !MayHaveDate([]byte("---\ndate:\n- 2020-01-01\ntags:\n- a\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false for a sequence-valued date, want true")
	}
}

func TestWithDate_StacksOverADateWrittenAsALiteralBlock(t *testing.T) {
	// The value is "|" here, so the line looks dated -- but replacing it leaves the
	// literal's continuation behind, and the reader folded the caller's date
	// together with the document's into one string.
	content := "---\ndate: |\n  2020-01-01\ntitle: One\n---\n\nbody\n"
	got := string(WithDate([]byte(content), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n" + content
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

// --- the opening delimiter has a narrower cutset than the closing one ---

// lineBreak is whitespace to str.rstrip() and also a character str.splitlines()
// breaks on, so the reader's first line ends before the delimiter. stripOnly is
// whitespace that is not a line break. Built from their code points rather than
// written literally, because neither survives a copy through a terminal.
var (
	lineBreak = string(rune(0x1c))
	stripOnly = string(rune(0x1f))
)

func TestMayHaveDate_TrueWhenALineBreakPrecedesTheDelimiter(t *testing.T) {
	// The reader's first line ends at this character, so the two ends do not agree
	// about where -- or whether -- the block starts: the reader resolves this whole
	// document to no frontmatter, authored date included.
	//
	// Unreadable rather than absent, deliberately. Reporting "no block" would have
	// the clock stamped on top, and the reader would then serve that ingest date in
	// place of the 2020-01-01 the document actually declares. Undated is the honest
	// answer; an explicit caller date still gets a block of its own, since it
	// outranks whatever the document is hiding.
	if !MayHaveDate([]byte(lineBreak + "---\ndate: 2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false behind a line break, want true")
	}
}

func TestWithDate_PrependsWhenALineBreakPrecedesTheDelimiter(t *testing.T) {
	got := string(WithDate([]byte(lineBreak+"---\ndate: 2020-01-01\n---\n\nbody\n"), "2026-06-01"))
	if !strings.HasPrefix(got, "---\ndate: 2026-06-01\n---\n\n") {
		t.Errorf("WithDate() = %q, want a fresh block the reader can see", got)
	}
}

func TestMayHaveDate_TrueWhenAStripOnlyCharacterPrecedesTheDelimiter(t *testing.T) {
	// str.rstrip() removes this one and str.splitlines() does not break on it, so
	// the reader does see this block. The two cutsets differ by exactly the break
	// characters, which is why they are two constants and not one.
	if !MayHaveDate([]byte(stripOnly + "---\ndate: 2020-01-01\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false behind a strip-only character, want true")
	}
}

// --- shapes that were load-bearing but unpinned ---

func TestWithDate_PrependedBlockKeepsALeadingBOM(t *testing.T) {
	// Prepending in front of the BOM leaves a stray U+FEFF in the body, which the
	// reader only strips as a prefix -- so it would reach the catalog summary.
	got := string(WithDate([]byte("\xef\xbb\xbf# Heading\n\nprose\n"), "2026-06-01"))
	want := "\xef\xbb\xbf---\ndate: 2026-06-01\n---\n\n# Heading\n\nprose\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_StacksOverABlockWithAnEmptyKey(t *testing.T) {
	// ": value" makes PyYAML raise, so this block is not a mapping and a date
	// written into it goes where nothing can read it.
	content := "---\n: value\n---\n\nbody\n"
	got := string(WithDate([]byte(content), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n" + content
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

// --- a top-level value the reader cannot parse ---

func TestMayHaveDate_TrueForAnUnquotedValueHoldingAColon(t *testing.T) {
	// "title: Q3: the plan" is a plain scalar with ": " in it, which PyYAML refuses
	// outright -- so the reader sees no mapping and this block cannot be edited. A
	// date inserted beside it lands in a block that still does not parse.
	if !MayHaveDate([]byte("---\ntitle: Q3: the plan\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false for an unparseable value, want true")
	}
}

func TestWithDate_StacksOverAnUnquotedValueHoldingAColon(t *testing.T) {
	// Stacking is what makes such a document datable at all: its own block never
	// parsed, so the date has to go somewhere the reader will look.
	content := "---\nauthor: bob\ntitle: Q3: the plan\n---\n\nbody\n"
	got := string(WithDate([]byte(content), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---\n\n" + content
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_InsertsBesideAQuotedValueHoldingAColon(t *testing.T) {
	// Quoted, so the reader parses it and the block stays editable.
	got := string(WithDate([]byte("---\ntitle: \"Q3: the plan\"\n---\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\ntitle: \"Q3: the plan\"\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_InsertsBesideAFlowValue(t *testing.T) {
	// A flow mapping as a *value* is valid YAML; only a flow mapping as the whole
	// block is beyond this scan.
	got := string(WithDate([]byte("---\ntags: {a: 1}\n---\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\ntags: {a: 1}\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_InsertsBesideALiteralScalarHoldingColons(t *testing.T) {
	// The prose inside a literal scalar is not a mapping entry and its colons are
	// not YAML's -- the rule above must only look at the block's own level, or a
	// document with a colon in its notes would stop being datable.
	content := "---\nnotes: |\n  see: here and: there\n---\n\nbody\n"
	got := string(WithDate([]byte(content), "2026-06-01"))
	want := "---\ndate: 2026-06-01\nnotes: |\n  see: here and: there\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

// --- a file with no trailing newline, and blank lines inside the block ---

func TestMayHaveDate_TrueForAFileWithNoTrailingNewline(t *testing.T) {
	// The closing delimiter is the last line and has no "\n" after it, which the
	// reader handles and so must the scan: splitlines() does not require one.
	if !MayHaveDate([]byte("---\ndate: 2020-01-01\n---")) {
		t.Error("MayHaveDate() = false without a trailing newline, want true")
	}
}

func TestWithDate_ReplacesADateOnTheLastLineWithNoNewline(t *testing.T) {
	// The rewritten line keeps the document's ending, and here there is none to
	// keep -- so no newline may be invented either, or the closing delimiter would
	// end up on the date's line.
	got := string(WithDate([]byte("---\ndate: 2020-01-01\n---"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n---"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestWithDate_InsertsIntoABlockOpeningWithABlankLine(t *testing.T) {
	// The blank line carries no level of its own, exactly as a comment does not.
	got := string(WithDate([]byte("---\n\ntitle: One\n---\n\nbody\n"), "2026-06-01"))
	want := "---\ndate: 2026-06-01\n\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}

func TestMayHaveDate_TrueForADateWhoseValueFollowsABlankLine(t *testing.T) {
	// A blank line does not end the value: the reader still reads the mapping below
	// as this key's, so the scan has to look past it too.
	if !MayHaveDate([]byte("---\ndate:\n\n  start: 2020-01-01\ntitle: One\n---\n\nbody\n")) {
		t.Error("MayHaveDate() = false for a value past a blank line, want true")
	}
}

func TestWithDate_ReplacesADateFollowedOnlyByAComment(t *testing.T) {
	// A comment cannot be a value, so this `date:` really is the null the reader
	// resolves it to -- and stays replaceable. The mirror of the case above.
	got := string(WithDate([]byte("---\ndate:\n  # not a value\ntitle: One\n---\n\nbody\n"),
		"2026-06-01"))
	want := "---\ndate: 2026-06-01\n  # not a value\ntitle: One\n---\n\nbody\n"
	if got != want {
		t.Errorf("WithDate() = %q, want %q", got, want)
	}
}
