package frontmatter

import (
	"bytes"
	"strings"
)

// ExtractTitle extracts the "title" value from YAML frontmatter in content.
// If frontmatter is absent or has no title key, falls back to the first H1
// heading ("# ...") in the body. Returns "" if neither is found.
func ExtractTitle(content []byte) string {
	// Strip UTF-8 BOM if present (common in Windows-edited files)
	content = bytes.TrimPrefix(content, []byte("\xef\xbb\xbf"))
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
