// Package e2e stages a knowledge base from a directory of real raw documents so
// a compile can be driven end to end against a live LLM.
//
// The corpus this harness reads is somebody's actual notes directory, not a
// fixture: staging therefore only ever reads from it and copies into a scratch
// KB, and the selection is deterministic so a run that fails on document 7 fails
// on the same document 7 next time.
//
// The selection and staging logic lives in this untagged file on purpose. The
// test that spends real LLM tokens sits behind the `locallm` build tag, but the
// part that decides which documents get compiled is ordinary logic that should be
// covered by the default `go test ./...` run.
package e2e

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

// ErrUnsafePath is returned when a document path would not stay inside the roots
// it gets joined onto. It is a sentinel because refusing to copy is the only
// thing standing between a bad Rel and a write outside the staged KB, and a
// caller — or a test — has to be able to tell that refusal apart from the
// not-found error the same path would incidentally produce.
var ErrUnsafePath = errors.New("e2e: unsafe document path")

// Doc is one document selected from the raw corpus.
type Doc struct {
	// Rel is the document's path relative to the corpus root, always in slash
	// form. It is also the value the engine is told to record as the source, and
	// that contract is slash-separated on every platform.
	Rel string
	// Bytes is the document's size on disk, carried so a harness can report the
	// volume it fed the model without stat-ing every file again.
	Bytes int64
}

// SampleOptions bounds a sample. The zero value selects every Markdown document
// in the corpus, which is the right default for a scale run and the wrong one for
// a smoke run — callers that pay per token should set both fields.
type SampleOptions struct {
	// MaxFiles caps how many documents are returned. 0 means no cap.
	MaxFiles int
	// MaxBytes drops any document larger than this many bytes, inclusive. 0 means
	// no ceiling. A single 300 KB meeting transcript can cost more wall-clock on
	// a local model than a dozen ordinary notes, so bounding size matters
	// independently of bounding count.
	MaxBytes int64
}

// Sample selects Markdown documents from the corpus rooted at root.
//
// Selection is deterministic and spread evenly across the sorted document list
// rather than taken from the front, so a small MaxFiles still reaches every
// top-level directory of the corpus instead of compiling one corner of it.
// Directories whose name begins with "." are skipped: `.git` and editor state
// are not corpus. So are symlinks and empty files, neither of which is a
// document a compile can be run over.
//
// A corpus with no Markdown in it yields an empty slice and no error; a root that
// does not exist is an error wrapping os.ErrNotExist, so a mistyped path cannot
// be mistaken for an empty corpus.
func Sample(root string, opt SampleOptions) ([]Doc, error) {
	if opt.MaxFiles < 0 {
		return nil, fmt.Errorf("e2e: MaxFiles must not be negative, got %d", opt.MaxFiles)
	}
	if opt.MaxBytes < 0 {
		return nil, fmt.Errorf("e2e: MaxBytes must not be negative, got %d", opt.MaxBytes)
	}

	var docs []Doc
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if p != root && strings.HasPrefix(d.Name(), ".") {
				return fs.SkipDir
			}
			return nil
		}
		// Regular files only. A symlink named *.md would be measured by its link
		// length here and followed when staged, so it both slips past MaxBytes and
		// drags in content from outside the corpus.
		if !d.Type().IsRegular() {
			return nil
		}
		if !strings.EqualFold(filepath.Ext(d.Name()), ".md") {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		// An empty file is not a compilable document: the engine rejects it with
		// EMPTY_CONTENT, which would fail a harness run for a reason that has
		// nothing to do with the compile under test.
		if info.Size() == 0 {
			return nil
		}
		if opt.MaxBytes > 0 && info.Size() > opt.MaxBytes {
			return nil
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		docs = append(docs, Doc{Rel: filepath.ToSlash(rel), Bytes: info.Size()})
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("e2e: walk corpus %q: %w", root, err)
	}

	sort.Slice(docs, func(i, j int) bool { return docs[i].Rel < docs[j].Rel })

	if opt.MaxFiles == 0 || len(docs) <= opt.MaxFiles {
		return docs, nil
	}
	// Even stride over the sorted list. Integer arithmetic keeps this exactly
	// reproducible; no rounding drift between runs.
	picked := make([]Doc, 0, opt.MaxFiles)
	for i := range opt.MaxFiles {
		picked = append(picked, docs[i*len(docs)/opt.MaxFiles])
	}
	return picked, nil
}

// kbSubdirs are the directories a staged KB starts with. The engine creates what
// it needs as it writes, but a harness that asserts "extract produced a file
// here" reads better against a KB whose shape is fixed up front than against one
// where a missing directory and a missing artifact look the same.
var kbSubdirs = []string{"raw", "wiki", "index", "extraction"}

// Stage lays out a knowledge base at kbDir and copies docs into it from the
// corpus at corpusRoot, each landing at <kbDir>/raw/<Doc.Rel>.
//
// corpusRoot is never written to. A Doc.Rel that is absolute, empty, or climbs
// out of the corpus with ".." is rejected rather than copied, because Rel reaches
// this function from a directory listing and gets joined onto two different
// roots.
func Stage(kbDir, corpusRoot string, docs []Doc) error {
	if err := checkKBOutsideCorpus(kbDir, corpusRoot); err != nil {
		return err
	}
	for _, d := range docs {
		if err := checkRel(d.Rel); err != nil {
			return err
		}
	}
	for _, sub := range kbSubdirs {
		if err := os.MkdirAll(filepath.Join(kbDir, sub), 0o755); err != nil {
			return fmt.Errorf("e2e: create %s: %w", sub, err)
		}
	}
	for _, d := range docs {
		src := filepath.Join(corpusRoot, filepath.FromSlash(d.Rel))
		body, err := os.ReadFile(src)
		if err != nil {
			return fmt.Errorf("e2e: read corpus doc %q: %w", d.Rel, err)
		}
		dst := filepath.Join(kbDir, "raw", filepath.FromSlash(d.Rel))
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return fmt.Errorf("e2e: create staging dir for %q: %w", d.Rel, err)
		}
		if err := os.WriteFile(dst, body, 0o644); err != nil {
			return fmt.Errorf("e2e: stage %q: %w", d.Rel, err)
		}
	}
	return nil
}

// checkKBOutsideCorpus refuses to stage into a directory that lives inside the
// corpus. Staging there would write into the notes directory the harness is
// supposed to only read, and the copies would then be picked up by the next
// Sample as if they were source documents.
func checkKBOutsideCorpus(kbDir, corpusRoot string) error {
	kbAbs, err := filepath.Abs(kbDir)
	if err != nil {
		return fmt.Errorf("e2e: resolve kb dir %q: %w", kbDir, err)
	}
	corpusAbs, err := filepath.Abs(corpusRoot)
	if err != nil {
		return fmt.Errorf("e2e: resolve corpus root %q: %w", corpusRoot, err)
	}
	rel, err := filepath.Rel(corpusAbs, kbAbs)
	if err != nil {
		// No relative path between them: different volumes, so not nested.
		return nil
	}
	if rel == "." || (rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))) {
		return fmt.Errorf("%w: kb dir %q is inside the corpus at %q", ErrUnsafePath, kbDir, corpusRoot)
	}
	return nil
}

// checkRel rejects any relative path that would not stay inside the roots it is
// joined onto. Every rejection wraps ErrUnsafePath.
func checkRel(rel string) error {
	if rel == "" {
		return fmt.Errorf("%w: empty", ErrUnsafePath)
	}
	if path.IsAbs(rel) || filepath.IsAbs(rel) {
		return fmt.Errorf("%w: %q must be relative to the corpus root", ErrUnsafePath, rel)
	}
	clean := path.Clean(rel)
	if clean == ".." || strings.HasPrefix(clean, "../") {
		return fmt.Errorf("%w: %q escapes the corpus root", ErrUnsafePath, rel)
	}
	return nil
}
