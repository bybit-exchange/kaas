package api

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/google/uuid"

	fmtitle "github.com/bybit-exchange/kaas/internal/frontmatter"
	"github.com/bybit-exchange/kaas/internal/store"
)

// richExtensions are document formats that require MarkItDown conversion.
var richExtensions = map[string]bool{
	".pdf": true, ".docx": true, ".pptx": true, ".xlsx": true,
	".html": true, ".htm": true, ".epub": true, ".rtf": true,
}

// allowedExtensions are the extensions accepted at the top level (includes .zip).
var allowedExtensions = map[string]bool{
	".md": true, ".txt": true, ".csv": true, ".zip": true,
	".pdf": true, ".docx": true, ".pptx": true, ".xlsx": true,
	".html": true, ".htm": true, ".epub": true, ".rtf": true,
}

// allowedInnerExtensions are extensions accepted inside a ZIP (excludes .zip).
var allowedInnerExtensions = map[string]bool{
	".md": true, ".txt": true, ".csv": true,
	".pdf": true, ".docx": true, ".pptx": true, ".xlsx": true,
	".html": true, ".htm": true, ".epub": true, ".rtf": true,
}

// submitFilesItem describes one processed file in the response.
type submitFilesItem struct {
	Name   string `json:"name"`
	ID     string `json:"id,omitempty"`
	Status string `json:"status"` // "uploaded" | "failed"
	Reason string `json:"reason,omitempty"`
}

// submitFilesResponse is the response for POST /api/submit/files.
type submitFilesResponse struct {
	Uploaded []submitFilesItem `json:"uploaded"`
	Failed   []submitFilesItem `json:"failed"`
}

// handleSubmitFiles serves POST /api/submit/files: multipart form upload with
// per-file processing (sha256 dedup, raw write, enqueue). ZIP files are
// extracted and each inner file is processed independently.
func (s *Server) handleSubmitFiles(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, s.cfg.Upload.MaxBodyBytes)

	if err := r.ParseMultipartForm(s.cfg.Upload.MaxBodyBytes); err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			writeErr(w, http.StatusRequestEntityTooLarge, "request body too large")
			return
		}
		writeErr(w, http.StatusBadRequest, "parse multipart form: "+err.Error())
		return
	}
	defer r.MultipartForm.RemoveAll()

	files := r.MultipartForm.File["files"]
	if len(files) == 0 {
		writeErr(w, http.StatusBadRequest, "no files provided")
		return
	}
	if len(files) > s.cfg.Upload.MaxFilesPerUpload {
		writeErr(w, http.StatusBadRequest, fmt.Sprintf("too many files (max %d)", s.cfg.Upload.MaxFilesPerUpload))
		return
	}

	resp := submitFilesResponse{
		Uploaded: []submitFilesItem{},
		Failed:   []submitFilesItem{},
	}

	for _, fh := range files {
		ext := strings.ToLower(filepath.Ext(fh.Filename))

		if !allowedExtensions[ext] {
			resp.Failed = append(resp.Failed, submitFilesItem{
				Name:   fh.Filename,
				Status: "failed",
				Reason: "extension not allowed",
			})
			continue
		}

		// Open the uploaded file.
		f, err := fh.Open()
		if err != nil {
			resp.Failed = append(resp.Failed, submitFilesItem{
				Name:   fh.Filename,
				Status: "failed",
				Reason: "open file: " + err.Error(),
			})
			continue
		}

		if ext == ".zip" {
			if fh.Size > s.cfg.Upload.MaxZipFileSize {
				f.Close()
				resp.Failed = append(resp.Failed, submitFilesItem{
					Name:   fh.Filename,
					Status: "failed",
					Reason: fmt.Sprintf("zip file too large (max %dMB)", s.cfg.Upload.MaxZipFileSize>>20),
				})
				continue
			}
			data, err := io.ReadAll(io.LimitReader(f, s.cfg.Upload.MaxZipFileSize+1))
			f.Close()
			if err != nil {
				resp.Failed = append(resp.Failed, submitFilesItem{
					Name:   fh.Filename,
					Status: "failed",
					Reason: "read zip: " + err.Error(),
				})
				continue
			}
			s.processZip(r, data, fh.Filename, &resp)
		} else {
			maxSize := s.cfg.Upload.MaxFileSize
			if richExtensions[ext] {
				maxSize = s.cfg.Upload.MaxRichFileSize
			}
			if fh.Size > maxSize {
				f.Close()
				resp.Failed = append(resp.Failed, submitFilesItem{
					Name:   fh.Filename,
					Status: "failed",
					Reason: fmt.Sprintf("file too large (max %dMB)", maxSize>>20),
				})
				continue
			}
			data, err := io.ReadAll(io.LimitReader(f, maxSize+1))
			f.Close()
			if err != nil {
				resp.Failed = append(resp.Failed, submitFilesItem{
					Name:   fh.Filename,
					Status: "failed",
					Reason: "read file: " + err.Error(),
				})
				continue
			}
			s.processFile(r, fh.Filename, ext, data, &resp)
		}
	}

	writeJSON(w, http.StatusAccepted, resp)
}

// processFile hashes, writes raw, and enqueues a single file. On submission
// failure the raw file is cleaned up.
func (s *Server) processFile(r *http.Request, name string, ext string, content []byte, resp *submitFilesResponse) {
	sum := sha256.Sum256(content)
	hash := hex.EncodeToString(sum[:])

	id := uuid.NewString()
	rawExt := ".md"
	if richExtensions[ext] {
		rawExt = ext
	}
	rawPath := filepath.Join(s.cfg.KBDir, "raw", id+rawExt)
	if err := os.MkdirAll(filepath.Dir(rawPath), 0o755); err != nil {
		resp.Failed = append(resp.Failed, submitFilesItem{
			Name:   name,
			Status: "failed",
			Reason: "create raw dir: " + err.Error(),
		})
		return
	}
	if err := os.WriteFile(rawPath, content, 0o644); err != nil {
		resp.Failed = append(resp.Failed, submitFilesItem{
			Name:   name,
			Status: "failed",
			Reason: "write raw: " + err.Error(),
		})
		return
	}

	task := &store.Task{
		ID:          id,
		Source:      "file",
		Title:       name,
		RawPath:     rawPath,
		ContentHash: hash,
		MaxAttempts: defaultMaxAttempts,
	}
	if richExtensions[ext] {
		task.FileTitle = strings.TrimSuffix(filepath.Base(name), ext)
	} else {
		task.FileTitle = fmtitle.ExtractTitle(content)
	}

	if err := s.q.Submit(r.Context(), task); err != nil {
		_ = os.Remove(rawPath)
		if errors.Is(err, store.ErrDuplicate) {
			resp.Failed = append(resp.Failed, submitFilesItem{
				Name:   name,
				Status: "failed",
				Reason: "content already submitted",
			})
			return
		}
		resp.Failed = append(resp.Failed, submitFilesItem{
			Name:   name,
			Status: "failed",
			Reason: "enqueue: " + err.Error(),
		})
		return
	}

	resp.Uploaded = append(resp.Uploaded, submitFilesItem{
		Name:   name,
		ID:     id,
		Status: "uploaded",
	})
}

// preparedFile holds validated ZIP entry data ready for the commit phase.
type preparedFile struct {
	Name    string
	Content []byte
	Hash    string
	Ext     string
}

// writtenFile tracks a file successfully written to disk in the commit phase.
type writtenFile struct {
	Name      string
	ID        string
	Hash      string
	RawPath   string
	FileTitle string
}

// processZip validates all ZIP entries then commits them atomically.
func (s *Server) processZip(r *http.Request, data []byte, zipName string, resp *submitFilesResponse) {
	prepared, errItem := s.validateZipEntries(data, zipName)
	if errItem != nil {
		resp.Failed = append(resp.Failed, *errItem)
		return
	}
	if len(prepared) == 0 {
		return
	}
	uploaded, errItem := s.commitFiles(r.Context(), prepared)
	if errItem != nil {
		resp.Failed = append(resp.Failed, *errItem)
		return
	}
	resp.Uploaded = append(resp.Uploaded, uploaded...)
}

// validateZipEntries validates all entries in a ZIP archive and returns prepared
// files ready for commit. If any entry fails validation, the entire ZIP is
// rejected (all-or-nothing).
func (s *Server) validateZipEntries(data []byte, zipName string) ([]preparedFile, *submitFilesItem) {
	reader, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, &submitFilesItem{
			Name:   zipName,
			Status: "failed",
			Reason: "invalid zip file: " + err.Error(),
		}
	}

	var prepared []preparedFile
	entryCount := 0
	var totalExtracted int64

	for _, f := range reader.File {
		entryCount++
		if entryCount > s.cfg.Upload.MaxZipEntries {
			return nil, &submitFilesItem{
				Name:   zipName,
				Status: "failed",
				Reason: fmt.Sprintf("zip contains too many entries (max %d)", s.cfg.Upload.MaxZipEntries),
			}
		}

		if f.FileInfo().IsDir() {
			continue
		}

		name := f.Name
		if strings.HasPrefix(name, "__MACOSX/") || strings.HasPrefix(filepath.Base(name), ".") {
			continue
		}

		if f.Mode()&os.ModeSymlink != 0 {
			continue
		}

		cleanName := filepath.Clean(name)
		if strings.Contains(cleanName, "..") {
			continue
		}

		baseName := filepath.Base(cleanName)
		if baseName == "." || baseName == "" {
			continue
		}

		ext := strings.ToLower(filepath.Ext(baseName))
		if !allowedInnerExtensions[ext] {
			return nil, &submitFilesItem{
				Name:   zipName,
				Status: "failed",
				Reason: "extension not allowed",
			}
		}

		totalExtracted += int64(f.UncompressedSize64)
		if totalExtracted > s.cfg.Upload.MaxZipExtractedSize {
			return nil, &submitFilesItem{
				Name:   zipName,
				Status: "failed",
				Reason: "zip extracted size exceeds limit",
			}
		}

		rc, err := f.Open()
		if err != nil {
			return nil, &submitFilesItem{
				Name:   zipName,
				Status: "failed",
				Reason: "open zip entry: " + err.Error(),
			}
		}
		entryMaxSize := s.cfg.Upload.MaxFileSize
		if richExtensions[ext] {
			entryMaxSize = s.cfg.Upload.MaxRichFileSize
		}
		content, err := io.ReadAll(io.LimitReader(rc, entryMaxSize+1))
		rc.Close()
		if err != nil {
			return nil, &submitFilesItem{
				Name:   zipName,
				Status: "failed",
				Reason: "read zip entry: " + err.Error(),
			}
		}
		if int64(len(content)) > entryMaxSize {
			return nil, &submitFilesItem{
				Name:   zipName,
				Status: "failed",
				Reason: fmt.Sprintf("file too large (max %dMB)", entryMaxSize>>20),
			}
		}

		sum := sha256.Sum256(content)
		prepared = append(prepared, preparedFile{
			Name:    baseName,
			Content: content,
			Hash:    hex.EncodeToString(sum[:]),
			Ext:     ext,
		})
	}

	return prepared, nil
}

// commitFiles writes all prepared files to disk then enqueues them.
// Duplicate files (ErrDuplicate) are silently skipped (idempotent).
func (s *Server) commitFiles(ctx context.Context, files []preparedFile) ([]submitFilesItem, *submitFilesItem) {
	// Sub-phase 2a: write all files to disk.
	written := make([]writtenFile, 0, len(files))
	for _, pf := range files {
		id := uuid.NewString()
		rawExt := ".md"
		if richExtensions[pf.Ext] {
			rawExt = pf.Ext
		}
		rawPath := filepath.Join(s.cfg.KBDir, "raw", id+rawExt)
		if err := os.MkdirAll(filepath.Dir(rawPath), 0o755); err != nil {
			s.rollbackFiles(written)
			return nil, &submitFilesItem{Name: pf.Name, Status: "failed", Reason: "create raw dir: " + err.Error()}
		}
		if err := os.WriteFile(rawPath, pf.Content, 0o644); err != nil {
			s.rollbackFiles(written)
			return nil, &submitFilesItem{Name: pf.Name, Status: "failed", Reason: "write raw: " + err.Error()}
		}
		var fileTitle string
		if richExtensions[pf.Ext] {
			fileTitle = strings.TrimSuffix(filepath.Base(pf.Name), pf.Ext)
		} else {
			fileTitle = fmtitle.ExtractTitle(pf.Content)
		}
		written = append(written, writtenFile{Name: pf.Name, ID: id, Hash: pf.Hash, RawPath: rawPath, FileTitle: fileTitle})
	}

	// Sub-phase 2b: enqueue all written files.
	var uploaded []submitFilesItem
	for _, wf := range written {
		task := &store.Task{
			ID:          wf.ID,
			Source:      "file",
			Title:       wf.Name,
			RawPath:     wf.RawPath,
			ContentHash: wf.Hash,
			MaxAttempts: defaultMaxAttempts,
		}
		task.FileTitle = wf.FileTitle
		if err := s.q.Submit(ctx, task); err != nil {
			if errors.Is(err, store.ErrDuplicate) {
				_ = os.Remove(wf.RawPath)
				continue
			}
			s.rollbackFiles(written)
			return nil, &submitFilesItem{Name: wf.Name, Status: "failed", Reason: "enqueue: " + err.Error()}
		}
		uploaded = append(uploaded, submitFilesItem{Name: wf.Name, ID: wf.ID, Status: "uploaded"})
	}

	return uploaded, nil
}

// rollbackFiles removes all raw files written during a failed commit phase.
func (s *Server) rollbackFiles(written []writtenFile) {
	for _, wf := range written {
		if err := os.Remove(wf.RawPath); err != nil && !errors.Is(err, os.ErrNotExist) {
			log.Printf("rollbackFiles: failed to remove %s (%q): %v", wf.RawPath, wf.Name, err)
		}
	}
}

type uploadConfigResponse struct {
	MaxFileSize       int64    `json:"max_file_size"`
	MaxRichFileSize   int64    `json:"max_rich_file_size"`
	MaxZipFileSize    int64    `json:"max_zip_file_size"`
	MaxFilesPerUpload int      `json:"max_files_per_upload"`
	AllowedExtensions []string `json:"allowed_extensions"`
}

func (s *Server) handleUploadConfig(w http.ResponseWriter, _ *http.Request) {
	exts := make([]string, 0, len(allowedExtensions))
	for ext := range allowedExtensions {
		exts = append(exts, ext)
	}
	sort.Strings(exts)

	writeJSON(w, http.StatusOK, uploadConfigResponse{
		MaxFileSize:       s.cfg.Upload.MaxFileSize,
		MaxRichFileSize:   s.cfg.Upload.MaxRichFileSize,
		MaxZipFileSize:    s.cfg.Upload.MaxZipFileSize,
		MaxFilesPerUpload: s.cfg.Upload.MaxFilesPerUpload,
		AllowedExtensions: exts,
	})
}
