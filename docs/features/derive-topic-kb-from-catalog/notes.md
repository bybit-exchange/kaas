# Derive Topic KB — Implementation Notes

## C6 verification

The nesting-is-inert property rests on two glob roots never reaching `<kb>/derived/`.
The Go side was spot-checked with:

```
grep -rn 'filepath.Join(.*"raw"' internal/
grep -rn '"wiki"' internal/api/wiki.go
```

### Raw writes — rooted at `filepath.Join(KBDir, "raw", ...)`

Every raw-file write in the Go layer goes to `filepath.Join(s.cfg.KBDir, "raw", ...)`:

```
internal/api/submit.go:60:          rawPath := filepath.Join(s.cfg.KBDir, "raw", id+".md")
internal/api/submit_files.go:159:   rawPath := filepath.Join(s.cfg.KBDir, "raw", id+".md")
internal/api/submit_files.go:357:   rawPath := filepath.Join(s.cfg.KBDir, "raw", id+".md")
internal/api/tasks.go:158:          rawDir  := filepath.Join(s.cfg.KBDir, "raw")
```

None of these reach `<kb>/derived/`.

### Wiki walker — rooted at `filepath.Join(s.cfg.KBDir, "wiki")`

```
internal/api/wiki.go:168:  wikiDir := filepath.Join(s.cfg.KBDir, "wiki")
internal/api/wiki.go:271:  wikiDir := filepath.Join(s.cfg.KBDir, "wiki")
```

Both walk roots are `<kb>/wiki`, not `<kb>`, so a derived KB at
`<kb>/derived/<slug>/wiki/` is unreachable. The same isolation holds for the
Python side: `KBStore._iter_raw_paths` globs `self.raw_dir` (`<base>/raw/`), and
`update_markdown_index` globs `store.wiki_dir` (`<base>/wiki/`) — both are locked
to the KB they are given. The regression tests in
`py/tests/test_derive_nesting.py` prove this for the Python layer.
