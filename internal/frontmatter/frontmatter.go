package frontmatter

import (
	"bytes"
	"regexp"
	"strconv"
	"strings"
)

const delim = "---"

// Every character Python's str.rstrip() removes from a delimiter line, which is
// the set str.isspace() accepts -- 29 code points, not the six ASCII ones. The
// reader these bytes are written for is py/src/kb_ai/_frontmatter.py, so the
// block boundaries have to be exactly the ones it recognises: a document closed
// with "--- " is a complete block there, and a narrower cutset here saw no
// block, stacked a second one on top, and shadowed the document's own date.
//
// Spelled out rather than taken from unicode.IsSpace, which disagrees at both
// ends: it omits U+001C-U+001F, which str.isspace() accepts, and it tracks a
// Unicode property table that can shift under a Go release while PyYAML's
// notion of a delimiter line does not.
const pythonSpace = "\t\n\v\f\r\u001c\u001d\u001e\u001f " +
	"\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005" +
	"\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"

// The characters `str.splitlines()` breaks a line on, minus "\n" and "\r" which
// this scan already treats as terminators. They are whitespace to `str.rstrip()`
// as well, so trimming them would make a line here look like a delimiter while
// the reader's line ended somewhere else entirely -- the two ends would disagree
// about where the block starts, and a date written on that assumption is written
// into a block the reader cannot see. A block containing one is reported as
// unreadable instead, which is the one answer that is safe in both directions.
//
// Generated from CPython rather than typed: the members are invisible control
// characters that do not survive a copy through a terminal.
const pythonLineBreaks = "\v\f\u001c\u001d\u001e\u0085\u2028\u2029"

// The same set as it applies *inside* a line, once the line's own terminator has
// been removed. A lone "\r" belongs here for the same reason: the reader's line
// would end at it where this scan's does not.
const lineBreakInside = pythonLineBreaks + "\r"

// bom is the UTF-8 byte order mark a Windows editor leaves at the head of a
// file. ExtractTitle has always stripped it; the block scan did not, so a BOM'd
// document read as having no frontmatter and had the ingest clock stamped over
// the date it declared. read_document_frontmatter strips it for the same reason.
const bom = "\xef\xbb\xbf"

// Characters that cannot appear in a plain block-mapping key. One of them means
// the line is flow syntax or a sequence entry: something PyYAML reads as a
// mapping and this scan cannot edit without destroying it.
const keyIndicators = "{}[],"

// HTML comments occupying the start of a document, blank lines included, so what
// follows them starts at line 0 for the block scan. Repeated, because re-ingesting
// a file that distill already ingested stacks a second comment above the first.
// (?s) because one comment may span lines: it holds a path, and a POSIX filename
// is allowed to contain a newline. Mirrors _LEADING_COMMENTS_RE in
// py/src/kb_ai/_frontmatter.py -- the reader that has to agree with us about where
// a document's frontmatter begins.
var leadingComments = regexp.MustCompile(`(?s)\A(?:<!--.*?-->[ \t]*\r?\n(?:[ \t]*\r?\n)*)+`)

// Field is one key/value pair for a frontmatter block WithDate creates.
type Field struct {
	Key   string
	Value string
}

// ExtractTitle extracts the "title" value from YAML frontmatter in content.
// If frontmatter is absent or has no title key, falls back to the first H1
// heading ("# ...") in the body. Returns "" if neither is found.
func ExtractTitle(content []byte) string {
	// Strip UTF-8 BOM if present (common in Windows-edited files)
	content = bytes.TrimPrefix(content, []byte(bom))
	title := extractFromFrontmatter(content)
	if title != "" {
		return title
	}
	return extractH1(content)
}

// extractFromFrontmatter looks for a leading "---\n" block and scans for
// a "title:" line within it.
func extractFromFrontmatter(content []byte) string {
	if !bytes.HasPrefix(content, []byte("---\n")) && !bytes.HasPrefix(content, []byte("---\r\n")) {
		return ""
	}
	rest := content[4:]
	end := bytes.Index(rest, []byte("\n---"))
	if end < 0 {
		return ""
	}
	block := rest[:end]

	for line := range bytes.Lines(block) {
		trimmed := strings.TrimSpace(string(line))
		if !strings.HasPrefix(trimmed, "title:") && !strings.HasPrefix(trimmed, "title :") {
			continue
		}
		idx := strings.Index(trimmed, ":")
		val := strings.TrimSpace(trimmed[idx+1:])
		return unquote(val)
	}
	return ""
}

// unquote removes surrounding single or double quotes if present.
func unquote(s string) string {
	if len(s) >= 2 {
		if (s[0] == '"' && s[len(s)-1] == '"') || (s[0] == '\'' && s[len(s)-1] == '\'') {
			return s[1 : len(s)-1]
		}
	}
	return s
}

// MayHaveDate reports whether content's leading frontmatter may already carry a
// date the reader can see, which is the question the caller actually has to
// answer: may the ingest clock be stamped here, or would that overwrite a date
// the document authored? It errs towards yes, so a document is left alone
// whenever this scan is not certain.
//
// Three ways to be dated:
//
//   - a "date" key at the block's own level with a value. A "date:" with nothing
//     after it does not count: PyYAML resolves it to None, which the write phase
//     cannot order by, so the clock is welcome to replace it.
//   - a block this scan cannot read -- flow syntax, a sequence, a key spelled
//     without the space YAML needs after the colon. PyYAML may well read a date
//     out of it, and reporting those as undated is how an authored date gets
//     shadowed by the ingest clock.
//   - nothing else. No block at all is undated, and a fresh one can be prepended
//     without touching anything the document said.
func MayHaveDate(content []byte) bool {
	openEnd, closeStart, indent, shape := block(content)
	switch shape {
	case noBlock:
		return false
	case opaqueBlock:
		return true
	}
	_, _, value, structured, found := dateLine(content[openEnd:closeStart], indent)
	if structured {
		// The value lives on the lines below the key, so this looks null to the scan
		// while the reader sees a mapping, a sequence or a literal there. Whatever it
		// is, it is the document's and the clock may not replace it.
		return true
	}
	return found && value != ""
}

// WithDate returns content carrying date in its leading YAML frontmatter, so the
// write phase can order this document against the others composed into an
// article. The extra fields are written only when a fresh block is created --
// a document that brought its own frontmatter keeps the keys it chose.
//
// Three shapes, in the order they are tried:
//
//   - a readable block already declaring a date: the value on the last such line
//     is replaced. Inserting a second "date:" would leave a duplicate key, and
//     PyYAML resolves duplicates to the last one -- which is why the last is also
//     the one that has to be rewritten.
//   - a readable block without a date: the line is inserted just below the
//     opening delimiter, at the level the block's own keys sit at. Stacking a
//     second block on top instead would push the document's own keys into the
//     body, where the catalog reads them as prose.
//   - no block, or one this scan cannot read: a fresh block is prepended,
//     carrying date plus any extra fields. Prepending is the wrong shape for a
//     readable block and the only safe one here -- inserting a block key above a
//     flow mapping is invalid YAML, which costs the document every label it had,
//     while a stacked block keeps all of its bytes and parses. Reaching this with
//     an unreadable block means the caller supplied a date explicitly, and an
//     explicit date outranks whatever the document may be hiding.
//
// A leading BOM stays at the head of the file, where a BOM means anything at all.
//
// Values are emitted double-quoted so a colon, a quote or a newline in a title
// cannot break the block. date is not quoted: the caller validated it as an ISO
// day or an RFC3339 stamp, both of which PyYAML resolves to a date object only
// while they are unquoted.
func WithDate(content []byte, date string, extra ...Field) []byte {
	openEnd, closeStart, indent, shape := block(content)
	if shape != mappingBlock {
		return prepend(content, date, extra)
	}

	start, end, _, structured, found := dateLine(content[openEnd:closeStart], indent)
	if structured {
		// The key's value is on the lines below it. Rewriting the key would orphan
		// them: a mapping loses its parent and the block stops parsing, and a
		// literal scalar folds the caller's date together with the document's.
		return prepend(content, date, extra)
	}
	if found {
		line := content[openEnd+start : openEnd+end]
		return join(content[:openEnd+start],
			[]byte(indent+"date: "+date+lineEnding(line)),
			content[openEnd+end:])
	}
	return join(content[:openEnd],
		[]byte(indent+"date: "+date+lineEnding(content[:openEnd])),
		content[openEnd:])
}

// prepend puts a fresh block at the head of content, behind a BOM if there is
// one: prepending in front of a BOM would leave a stray U+FEFF in the body, which
// the reader only strips as a prefix and would otherwise carry into a summary.
func prepend(content []byte, date string, extra []Field) []byte {
	var b bytes.Buffer
	if bytes.HasPrefix(content, []byte(bom)) {
		b.WriteString(bom)
		content = content[len(bom):]
	}
	b.WriteString(delim + "\n")
	b.WriteString("date: " + date + "\n")
	for _, f := range extra {
		if f.Value == "" {
			continue
		}
		b.WriteString(f.Key + ": " + strconv.Quote(f.Value) + "\n")
	}
	b.WriteString(delim + "\n\n")
	b.Write(content)
	return b.Bytes()
}

// blockShape says how much of a leading frontmatter block this scan understood.
type blockShape int

const (
	// noBlock: content does not open with a delimiter, or the block is never
	// closed -- exactly what split_frontmatter treats as "no frontmatter".
	noBlock blockShape = iota
	// mappingBlock: a complete block whose keys are plain "key: value" lines, so
	// a date can be read out of it and written into it.
	mappingBlock
	// opaqueBlock: a complete block PyYAML may read as a mapping while this scan
	// cannot -- flow syntax, a sequence, a key missing the space after its colon.
	opaqueBlock
)

// block locates a leading frontmatter block, returning the offset just past the
// opening delimiter line, the offset at which the closing delimiter line starts,
// and the indentation the block's keys sit at.
//
// A BOM and a provenance comment ahead of the block are stepped over, because the
// reader does the same: distill prepends "<!-- source: ... -->" to every file it
// ingests, and reading a re-submitted one as having no frontmatter is how an
// authored date ends up shadowed by the ingest clock.
//
// Lines are split on "\n" alone, where Python also splits on a lone "\r": a
// document using classic Mac line endings is seen here as having no block, so a
// fresh one goes on top and the document's own keys stay in the body -- labels
// lost, no content.
func block(content []byte) (openEnd, closeStart int, indent string, shape blockShape) {
	off := 0
	if bytes.HasPrefix(content, []byte(bom)) {
		off = len(bom)
	}
	rest := content[off:]
	if openEnd, closeStart, indent, shape = scanBlock(rest); shape != noBlock {
		return openEnd + off, closeStart + off, indent, shape
	}
	if m := leadingComments.FindIndex(rest); m != nil {
		if openEnd, closeStart, indent, shape = scanBlock(rest[m[1]:]); shape != noBlock {
			return openEnd + m[1] + off, closeStart + m[1] + off, indent, shape
		}
	}
	return 0, 0, "", noBlock
}

// scanBlock is block() without the BOM and comment retries. The opening delimiter
// is matched on a full trim and the closing one on a right trim only, so an
// indented "---" opens a block but never closes one -- split_frontmatter's rule.
//
// The block's level comes from its first line that is a plain key, not its first
// non-blank line. A YAML comment or a blank line carries indentation of its own
// and none of the block's: taking the level from "  # written by hand" put the
// inserted date two columns in, above a key at column 0, and PyYAML rejected the
// whole block -- a document that arrived dated and titled came back with neither.
//
// A block whose first meaningful line is not a plain key is opaque rather than
// absent, because the difference matters to the caller: a block that is merely
// absent can be replaced, and one that is opaque may be hiding a date.
func scanBlock(content []byte) (openEnd, closeStart int, indent string, shape blockShape) {
	first, decided := true, false
	shape = mappingBlock
	for i := 0; i < len(content); {
		end := i + bytes.IndexByte(content[i:], '\n') + 1
		if end == i {
			end = len(content)
		}
		line := content[i:end]
		if bytes.ContainsAny(withoutTerminator(line), lineBreakInside) {
			// The reader's line ends inside this one, so the two ends do not agree
			// about the block's extent. Keep scanning for the closing delimiter, but
			// nothing in here may be edited on an offset this scan computed.
			shape = opaqueBlock
		}
		switch {
		case first:
			if string(bytes.Trim(line, pythonSpace)) != delim {
				return 0, 0, "", noBlock
			}
			openEnd, first = end, false
		case string(bytes.TrimRight(line, pythonSpace)) == delim:
			if shape == mappingBlock && !valuesParse(content[openEnd:i], indent) {
				shape = opaqueBlock
			}
			return openEnd, i, indent, shape
		case decided:
			// The level is settled; nothing later can move it.
		default:
			switch kind, at := classify(line); kind {
			case skipLine:
			case keyLine:
				indent, decided = at, true
			default:
				// An empty block would have been decided by no line at all, and
				// stays a mapping: inserting a key into it produces one.
				shape, decided = opaqueBlock, true
			}
		}
		i = end
	}
	return 0, 0, "", noBlock
}

// valuesParse reports whether every entry at the block's own level carries a
// value the reader can parse. One that cannot makes PyYAML refuse the whole block,
// so the document has no readable frontmatter and writing a date into it puts the
// date somewhere nothing will look -- where stacking a block above makes such a
// document datable for the first time.
//
// The one shape checked is a plain scalar holding ": " or ending in ":", which
// PyYAML reads as a second mapping value and rejects: `title: Q3: the plan`, a
// thoroughly ordinary thing to write. Quoted and flow values are exempt because
// both parse. Only the block's own level is examined: the prose inside a literal
// scalar is indented deeper, its colons are not YAML's, and a document with a
// colon in its notes has to stay datable.
//
// Not a YAML validator, and not trying to be. It closes the one invalid shape
// common enough to matter; anything else it misses degrades a document to undated,
// which is what it already was.
func valuesParse(block []byte, indent string) bool {
	for i := 0; i < len(block); {
		lineEnd := i + bytes.IndexByte(block[i:], '\n') + 1
		if lineEnd == i {
			lineEnd = len(block)
		}
		line := block[i:lineEnd]
		i = lineEnd
		if lineIndent(line) != indent {
			continue
		}
		_, value, ok := splitKeyValue(line)
		if !ok || value == "" || strings.HasPrefix(value, `"`) ||
			strings.HasPrefix(value, "'") || strings.ContainsAny(value[:1], "{[") {
			continue
		}
		if strings.Contains(value, ": ") || strings.HasSuffix(value, ":") {
			return false
		}
	}
	return true
}

// lineKind is what one line inside a block tells us about the block's level.
type lineKind int

const (
	// skipLine carries no level of its own: blank, or a YAML comment.
	skipLine lineKind = iota
	// keyLine is a plain "key: value" entry, and its indentation is the block's.
	keyLine
	// otherLine is anything else, which makes the block opaque.
	otherLine
)

// classify reports what kind of line this is and, for a key, the indentation it
// sits at.
func classify(line []byte) (lineKind, string) {
	trimmed := bytes.TrimRight(bytes.TrimLeft(line, " \t"), pythonSpace)
	switch {
	case len(trimmed) == 0:
		return skipLine, ""
	case trimmed[0] == '#':
		return skipLine, ""
	case trimmed[0] == '-' && (len(trimmed) == 1 || trimmed[1] == ' ' || trimmed[1] == '\t'):
		// A sequence entry, and "- date: 2020-01-01" reads as a key otherwise: the
		// colon is there and the space after it is too. The block is a sequence, so
		// the reader sees no mapping and a date inserted beside it is lost.
		return otherLine, ""
	}
	key, _, ok := splitKeyValue(line)
	if !ok || key == "" || strings.ContainsAny(key, keyIndicators) {
		return otherLine, ""
	}
	indent := lineIndent(line)
	if strings.ContainsRune(indent, '\t') {
		// YAML forbids a tab as indentation, so the reader sees no mapping here
		// whatever this line looks like. Inserting a date into it would put the
		// date somewhere nothing can parse and lose it with no sign of it.
		return otherLine, ""
	}
	return keyLine, indent
}

// dateLine locates the block's own "date" key, returning the bounds of its whole
// line (trailing newline included) and the raw value after the colon.
//
// The *last* such line, because PyYAML resolves a duplicate key to the last
// occurrence: rewriting the first one left the document's own date standing and
// dropped the caller's, which is the same silent loss that inserting a second
// key would have caused.
//
// Only a key at the block's indentation counts. A deeper one belongs to a nested
// mapping or sits inside a literal scalar, where it is neither the document's
// date nor ours to rewrite: treating "meta.date" as the document's left the
// document undated with nothing saying so, and rewriting it deleted a key the
// document meant to keep.
//
// The key is unquoted before comparison, so `"date":` counts as the same key YAML
// resolves it to. Inserting a second one instead would leave a duplicate that
// PyYAML settles in the document's favour, silently dropping the caller's date.
// The space-before-colon spelling is accepted for the same reason
// extractFromFrontmatter accepts it.
// structured is true when the value is not on the date line at all but on the
// lines below it -- a nested mapping, a sequence, a literal scalar. Such a line
// looks null (or looks like "|") to a scan that stops at the newline, and
// rewriting it orphans the value: the block stops parsing and the document loses
// every label it had. The caller must leave the block alone instead.
func dateLine(block []byte, indent string) (start, end int, value string, structured, ok bool) {
	for i := 0; i < len(block); {
		lineEnd := i + bytes.IndexByte(block[i:], '\n') + 1
		if lineEnd == i {
			lineEnd = len(block)
		}
		line := block[i:lineEnd]
		if lineIndent(line) == indent {
			if key, val, found := splitKeyValue(line); found && key == "date" {
				start, end, value, ok = i, lineEnd, val, true
				structured = valueContinues(block[lineEnd:], indent)
			}
		}
		i = lineEnd
	}
	return start, end, value, structured, ok
}

// valueContinues reports whether the lines after a key carry that key's value: a
// line indented deeper than the block, or a sequence entry at the block's own
// level. Blank lines and comments are stepped over, because neither can be a
// value -- so `date:` followed by a comment and then another key is still the
// null the reader resolves it to, and stays replaceable.
func valueContinues(rest []byte, indent string) bool {
	for i := 0; i < len(rest); {
		lineEnd := i + bytes.IndexByte(rest[i:], '\n') + 1
		if lineEnd == i {
			lineEnd = len(rest)
		}
		line := rest[i:lineEnd]
		trimmed := bytes.TrimRight(bytes.TrimLeft(line, " \t"), pythonSpace)
		if len(trimmed) == 0 || trimmed[0] == '#' {
			i = lineEnd
			continue
		}
		at := lineIndent(line)
		if len(at) > len(indent) && strings.HasPrefix(at, indent) {
			return true
		}
		return at == indent && trimmed[0] == '-' &&
			(len(trimmed) == 1 || trimmed[1] == ' ' || trimmed[1] == '\t')
	}
	return false
}

// splitKeyValue splits a "key: value" line into its unquoted key and its raw
// value. ok is false for a line that holds no colon, and for one whose colon is
// not followed by a space, a tab or the end of the line: YAML needs that space
// to read a mapping entry, so `date:2020-01-01` is a plain scalar and the
// document has no mapping at all. Reading it as a key claimed the document was
// dated when the reader could see no date, and the stamp that should have
// replaced it never landed.
func splitKeyValue(line []byte) (key, value string, ok bool) {
	s := strings.TrimRight(strings.TrimLeft(string(line), " \t"), pythonSpace)
	idx := strings.Index(s, ":")
	if idx < 0 {
		return "", "", false
	}
	rest := s[idx+1:]
	if rest != "" && rest[0] != ' ' && rest[0] != '\t' {
		return "", "", false
	}
	return unquote(strings.TrimSpace(s[:idx])), strings.TrimSpace(rest), true
}

// withoutTerminator returns a line without the newline that ends it, so a scan
// for characters the reader would have broken the line on does not trip over the
// break this scan already accounted for.
func withoutTerminator(line []byte) []byte {
	line = bytes.TrimSuffix(line, []byte("\n"))
	return bytes.TrimSuffix(line, []byte("\r"))
}

// lineIndent returns the spaces and tabs a line opens with.
func lineIndent(line []byte) string {
	return string(line[:len(line)-len(bytes.TrimLeft(line, " \t"))])
}

// lineEnding returns the newline the given slice ends with, so a rewritten line
// keeps the document's own convention. "" when there is none.
func lineEnding(line []byte) string {
	switch {
	case bytes.HasSuffix(line, []byte("\r\n")):
		return "\r\n"
	case bytes.HasSuffix(line, []byte("\n")):
		return "\n"
	}
	return ""
}

func join(parts ...[]byte) []byte {
	size := 0
	for _, p := range parts {
		size += len(p)
	}
	out := make([]byte, 0, size)
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

// extractH1 finds the first "# " heading line in content.
func extractH1(content []byte) string {
	for line := range bytes.Lines(content) {
		s := strings.TrimSpace(string(line))
		if strings.HasPrefix(s, "# ") {
			return strings.TrimSpace(s[2:])
		}
	}
	return ""
}
