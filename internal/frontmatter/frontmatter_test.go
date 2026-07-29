package frontmatter

import "testing"

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
