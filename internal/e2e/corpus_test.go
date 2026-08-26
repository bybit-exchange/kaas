package e2e

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// writeCorpus builds a corpus tree under a fresh temp dir. Keys are slash paths
// relative to the root; values are the file bodies.
func writeCorpus(t *testing.T, files map[string]string) string {
	t.Helper()
	root := t.TempDir()
	for rel, body := range files {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatalf("mkdir %s: %v", filepath.Dir(p), err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatalf("write %s: %v", p, err)
		}
	}
	return root
}

func rels(docs []Doc) []string {
	out := make([]string, len(docs))
	for i, d := range docs {
		out[i] = d.Rel
	}
	return out
}

func TestSampleMissingRoot(t *testing.T) {
	_, err := Sample(filepath.Join(t.TempDir(), "absent"), SampleOptions{})
	if err == nil {
		t.Fatal("Sample on a missing root returned nil error")
	}
	if !errors.Is(err, os.ErrNotExist) {
		t.Errorf("err = %v, want it to wrap os.ErrNotExist so a caller can tell "+
			"a bad path from an empty corpus", err)
	}
}

func TestSampleEmptyCorpusIsNotAnError(t *testing.T) {
	docs, err := Sample(t.TempDir(), SampleOptions{})
	if err != nil {
		t.Fatalf("Sample on an empty dir: %v", err)
	}
	if len(docs) != 0 {
		t.Errorf("docs = %v, want none", rels(docs))
	}
}

func TestSampleTakesOnlyMarkdown(t *testing.T) {
	root := writeCorpus(t, map[string]string{
		"docs/keep.md":       "a",
		"docs/skip.json":     "{}",
		"docs/skip.txt":      "b",
		"docs/skip.markdown": "c",
		"docs/UPPER.MD":      "d",
	})

	docs, err := Sample(root, SampleOptions{})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	// UPPER.MD counts: the extension test is case-insensitive, and a corpus on a
	// case-insensitive filesystem should not sample differently than on ext4.
	want := []string{"docs/UPPER.MD", "docs/keep.md"}
	if got := rels(docs); !reflect.DeepEqual(got, want) {
		t.Errorf("docs = %v, want %v", got, want)
	}
}

func TestSampleRecordsSizeAndSortsByPath(t *testing.T) {
	root := writeCorpus(t, map[string]string{
		"meetings/m.md": "0123456789",
		"docs/a.md":     "abc",
		"tasks/t.md":    "z",
	})

	docs, err := Sample(root, SampleOptions{})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	want := []Doc{
		{Rel: "docs/a.md", Bytes: 3},
		{Rel: "meetings/m.md", Bytes: 10},
		{Rel: "tasks/t.md", Bytes: 1},
	}
	if !reflect.DeepEqual(docs, want) {
		t.Errorf("docs = %+v, want %+v", docs, want)
	}
}

func TestSampleRelIsAlwaysSlashSeparated(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a/b/c/deep.md": "x"})

	docs, err := Sample(root, SampleOptions{})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	// Rel travels to the Python engine as a `source` value, which is slash-form
	// on every platform, so it must not pick up the host separator.
	if len(docs) != 1 || docs[0].Rel != "a/b/c/deep.md" {
		t.Errorf("docs = %v, want [a/b/c/deep.md]", rels(docs))
	}
}

func TestSampleMaxBytesDropsOversizedFiles(t *testing.T) {
	root := writeCorpus(t, map[string]string{
		"a.md": "12345",  // 5 bytes, under
		"b.md": "123456", // 6 bytes, exactly at the ceiling
		"c.md": "1234567",
	})

	docs, err := Sample(root, SampleOptions{MaxBytes: 6})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	// The ceiling is inclusive: a file of exactly MaxBytes is kept.
	want := []string{"a.md", "b.md"}
	if got := rels(docs); !reflect.DeepEqual(got, want) {
		t.Errorf("docs = %v, want %v", got, want)
	}
}

func TestSampleZeroMaxBytesMeansNoCeiling(t *testing.T) {
	root := writeCorpus(t, map[string]string{"big.md": "0123456789"})

	docs, err := Sample(root, SampleOptions{MaxBytes: 0})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	if got := rels(docs); !reflect.DeepEqual(got, []string{"big.md"}) {
		t.Errorf("docs = %v, want [big.md]", got)
	}
}

func TestSampleSpreadsAcrossTheCorpusRatherThanTakingAPrefix(t *testing.T) {
	// Nine files in three directories. A prefix-taking sampler would return three
	// files all from aaa/, which would exercise one kind of document only.
	files := map[string]string{}
	for _, dir := range []string{"aaa", "mmm", "zzz"} {
		for _, n := range []string{"1", "2", "3"} {
			files[dir+"/"+n+".md"] = "x"
		}
	}
	root := writeCorpus(t, files)

	docs, err := Sample(root, SampleOptions{MaxFiles: 3})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	want := []string{"aaa/1.md", "mmm/1.md", "zzz/1.md"}
	if got := rels(docs); !reflect.DeepEqual(got, want) {
		t.Errorf("docs = %v, want one file from each directory %v", got, want)
	}
}

func TestSampleMaxFilesAboveCorpusSizeReturnsEverything(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a.md": "x", "b.md": "y"})

	docs, err := Sample(root, SampleOptions{MaxFiles: 99})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	if got := rels(docs); !reflect.DeepEqual(got, []string{"a.md", "b.md"}) {
		t.Errorf("docs = %v, want both files", got)
	}
}

func TestSampleZeroMaxFilesMeansNoLimit(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a.md": "x", "b.md": "y", "c.md": "z"})

	docs, err := Sample(root, SampleOptions{MaxFiles: 0})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	if got := rels(docs); !reflect.DeepEqual(got, []string{"a.md", "b.md", "c.md"}) {
		t.Errorf("docs = %v, want all three", got)
	}
}

func TestSampleNegativeMaxFilesIsRejected(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a.md": "x"})

	if _, err := Sample(root, SampleOptions{MaxFiles: -1}); err == nil {
		t.Error("Sample with MaxFiles=-1 returned nil error")
	}
	if _, err := Sample(root, SampleOptions{MaxBytes: -1}); err == nil {
		t.Error("Sample with MaxBytes=-1 returned nil error")
	}
}

func TestSampleIsDeterministic(t *testing.T) {
	files := map[string]string{}
	for _, dir := range []string{"docs", "local", "meetings", "tasks"} {
		for i := '0'; i <= '9'; i++ {
			files[dir+"/"+string(i)+".md"] = "body"
		}
	}
	root := writeCorpus(t, files)

	first, err := Sample(root, SampleOptions{MaxFiles: 7})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	for i := range 5 {
		again, err := Sample(root, SampleOptions{MaxFiles: 7})
		if err != nil {
			t.Fatalf("Sample re-run %d: %v", i, err)
		}
		if !reflect.DeepEqual(first, again) {
			t.Fatalf("re-run %d = %v, first run = %v; the sample must not vary "+
				"between runs or a failure cannot be reproduced", i, rels(again), rels(first))
		}
	}
	if len(first) != 7 {
		t.Errorf("len(docs) = %d, want 7", len(first))
	}
}

func TestSampleSkipsDotDirectories(t *testing.T) {
	root := writeCorpus(t, map[string]string{
		"real.md":          "x",
		".git/hooks/hi.md": "y",
		".obsidian/n.md":   "z",
	})

	docs, err := Sample(root, SampleOptions{})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	if got := rels(docs); !reflect.DeepEqual(got, []string{"real.md"}) {
		t.Errorf("docs = %v, want [real.md]; tool directories are not corpus", got)
	}
}

func TestSampleSkipsEmptyDocuments(t *testing.T) {
	root := writeCorpus(t, map[string]string{"empty.md": "", "real.md": "x"})

	docs, err := Sample(root, SampleOptions{})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	// The engine rejects empty content outright, so an empty file would fail a
	// harness run for a reason unrelated to the compile.
	if got := rels(docs); !reflect.DeepEqual(got, []string{"real.md"}) {
		t.Errorf("docs = %v, want [real.md]", got)
	}
}

func TestSampleSkipsSymlinks(t *testing.T) {
	root := writeCorpus(t, map[string]string{"real.md": "0123456789"})

	// A symlink to a file well over the ceiling. Its own lstat size is the length
	// of the target path, so a sampler that does not check the file type both
	// measures the wrong thing and stages content from outside the corpus.
	outside := filepath.Join(t.TempDir(), "huge.md")
	if err := os.WriteFile(outside, []byte(strings.Repeat("x", 5000)), 0o644); err != nil {
		t.Fatalf("write outside file: %v", err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "link.md")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	docs, err := Sample(root, SampleOptions{MaxBytes: 100})
	if err != nil {
		t.Fatalf("Sample: %v", err)
	}
	if got := rels(docs); !reflect.DeepEqual(got, []string{"real.md"}) {
		t.Errorf("docs = %v, want [real.md]; a symlink is not a corpus document", got)
	}
}

func TestStageRejectsAKBInsideTheCorpus(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a.md": "x"})

	// Staging here would write into the notes directory the harness only reads,
	// and the copies would be sampled as source documents on the next run.
	for _, kb := range []string{root, filepath.Join(root, "kb"), filepath.Join(root, "docs", "deep", "kb")} {
		err := Stage(kb, root, []Doc{{Rel: "a.md", Bytes: 1}})
		if !errors.Is(err, ErrUnsafePath) {
			t.Errorf("Stage into %q: err = %v, want it to wrap ErrUnsafePath", kb, err)
		}
	}

	// A sibling of the corpus is fine — only nesting is the problem.
	sibling := filepath.Join(filepath.Dir(root), "kb-sibling")
	if err := Stage(sibling, root, []Doc{{Rel: "a.md", Bytes: 1}}); err != nil {
		t.Errorf("Stage into a sibling directory: %v", err)
	}
}

func TestStageCopiesDocsUnderRawAndLeavesTheSourceAlone(t *testing.T) {
	root := writeCorpus(t, map[string]string{
		"docs/a.md":     "alpha body",
		"meetings/b.md": "beta body",
		"ignored.md":    "not sampled",
	})
	kb := filepath.Join(t.TempDir(), "kb")

	docs := []Doc{{Rel: "docs/a.md", Bytes: 10}, {Rel: "meetings/b.md", Bytes: 9}}
	if err := Stage(kb, root, docs); err != nil {
		t.Fatalf("Stage: %v", err)
	}

	for rel, want := range map[string]string{
		"docs/a.md":     "alpha body",
		"meetings/b.md": "beta body",
	} {
		got, err := os.ReadFile(filepath.Join(kb, "raw", filepath.FromSlash(rel)))
		if err != nil {
			t.Fatalf("read staged %s: %v", rel, err)
		}
		if string(got) != want {
			t.Errorf("staged %s = %q, want %q", rel, got, want)
		}
	}

	// A doc that was not sampled must not appear, or the KB under test is not
	// the sample the caller asked for.
	if _, err := os.Stat(filepath.Join(kb, "raw", "ignored.md")); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("stat unsampled doc: err = %v, want os.ErrNotExist", err)
	}

	// The corpus is somebody's real notes directory; staging must be read-only
	// against it.
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatalf("read corpus root: %v", err)
	}
	if len(entries) != 3 {
		t.Errorf("corpus root now has %d entries, want the original 3", len(entries))
	}
}

func TestStageCreatesTheDirectoriesTheEngineDoesNotCreateItself(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a.md": "x"})
	kb := filepath.Join(t.TempDir(), "kb")

	if err := Stage(kb, root, []Doc{{Rel: "a.md", Bytes: 1}}); err != nil {
		t.Fatalf("Stage: %v", err)
	}
	for _, dir := range []string{"raw", "wiki", "index", "extraction"} {
		info, err := os.Stat(filepath.Join(kb, dir))
		if err != nil {
			t.Errorf("stat %s: %v", dir, err)
			continue
		}
		if !info.IsDir() {
			t.Errorf("%s is not a directory", dir)
		}
	}
}

func TestStageRejectsAnEscapingRel(t *testing.T) {
	// The escaping rels below are made to resolve to a file that really exists,
	// one level above the corpus root. Without that, Stage refuses them for the
	// wrong reason — os.ReadFile fails on the missing file and returns an error
	// either way — and a Stage with its containment check removed still passes.
	parent := t.TempDir()
	root := filepath.Join(parent, "corpus")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatalf("mkdir corpus: %v", err)
	}
	if err := os.WriteFile(filepath.Join(root, "a.md"), []byte("x"), 0o644); err != nil {
		t.Fatalf("write corpus doc: %v", err)
	}
	const secret = "must not be staged"
	if err := os.WriteFile(filepath.Join(parent, "outside.md"), []byte(secret), 0o644); err != nil {
		t.Fatalf("write outside doc: %v", err)
	}

	kb := filepath.Join(t.TempDir(), "kb")
	for _, rel := range []string{"../outside.md", "docs/../../outside.md", "/a.md", ""} {
		err := Stage(kb, root, []Doc{{Rel: rel}})
		if !errors.Is(err, ErrUnsafePath) {
			t.Errorf("Stage with Rel=%q: err = %v, want it to wrap ErrUnsafePath; "+
				"a non-nil error alone can come from the failed read instead of the refusal",
				rel, err)
		}
	}

	// The effect, not just the error: nothing outside <kb>/raw was written, and
	// the file above the corpus root was not copied anywhere.
	var strays []string
	err := filepath.WalkDir(kb, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		rel, relErr := filepath.Rel(kb, p)
		if relErr != nil {
			return relErr
		}
		strays = append(strays, filepath.ToSlash(rel))
		return nil
	})
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("walk kb: %v", err)
	}
	if len(strays) != 0 {
		t.Errorf("Stage wrote %v after refusing every document; it must write nothing", strays)
	}
	if body, err := os.ReadFile(filepath.Join(parent, "outside.md")); err != nil {
		t.Errorf("read outside doc: %v", err)
	} else if string(body) != secret {
		t.Errorf("the file above the corpus root was modified: %q", body)
	}
}

func TestStageReportsAMissingSourceFile(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a.md": "x"})
	kb := filepath.Join(t.TempDir(), "kb")

	err := Stage(kb, root, []Doc{{Rel: "gone.md", Bytes: 1}})
	if err == nil {
		t.Fatal("Stage of an absent doc returned nil error")
	}
	if !errors.Is(err, os.ErrNotExist) {
		t.Errorf("err = %v, want it to wrap os.ErrNotExist", err)
	}
}

func TestStageWithNoDocsStillLaysOutTheKB(t *testing.T) {
	root := writeCorpus(t, map[string]string{"a.md": "x"})
	kb := filepath.Join(t.TempDir(), "kb")

	if err := Stage(kb, root, nil); err != nil {
		t.Fatalf("Stage: %v", err)
	}
	if _, err := os.Stat(filepath.Join(kb, "raw")); err != nil {
		t.Errorf("stat raw: %v", err)
	}
}
