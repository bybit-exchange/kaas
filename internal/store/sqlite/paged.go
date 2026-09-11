package sqlite

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
)

// pagedQueryConfig describes a paged, filtered, sorted query over a single table.
//
// Safety: Table, Columns, AllowedSort values, and DefaultSort are interpolated
// directly into SQL. Callers must pass trusted constant values — never user input.
type pagedQueryConfig struct {
	Table       string            // table name, e.g. "build_jobs"
	Columns     string            // SELECT column list, e.g. buildJobColumns
	Where       []string          // WHERE clause fragments (already parameterized)
	Args        []any             // positional args matching the Where fragments
	AllowedSort map[string]string // client key → SQL column, e.g. {"title": "title"}
	DefaultSort string            // fallback sort column, e.g. "created_at"
	SortBy      string            // client-requested sort key
	SortDir     string            // "asc" or "desc"
	Limit       int
	Offset      int
}

// pagedQueryResult holds the total count and the rows query + args.
// The caller runs the rows query and scans with its own type-specific scanner.
type pagedQueryResult struct {
	Total    int
	RowsSQL  string
	RowsArgs []any
}

// buildPagedQuery executes the COUNT query and prepares the SELECT query.
// Callers must pass trusted constant values — never user input.
func buildPagedQuery(ctx context.Context, db *sql.DB, cfg pagedQueryConfig) (*pagedQueryResult, error) {
	var whereClause string
	if len(cfg.Where) > 0 {
		whereClause = ` WHERE ` + strings.Join(cfg.Where, ` AND `)
	}

	// Count total matching rows.
	countQ := `SELECT COUNT(*) FROM ` + cfg.Table + whereClause
	var total int
	if err := db.QueryRowContext(ctx, countQ, cfg.Args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("paged query count %s: %w", cfg.Table, err)
	}

	// Determine sort column and direction.
	// sortCol is always from AllowedSort (a trusted constant map) or DefaultSort.
	sortCol := cfg.DefaultSort
	if col, ok := cfg.AllowedSort[cfg.SortBy]; ok {
		sortCol = col
	}
	sortDir := "DESC"
	if cfg.SortDir == "asc" {
		sortDir = "ASC"
	}

	// Build the SELECT.
	selectQ := `SELECT ` + cfg.Columns + ` FROM ` + cfg.Table + whereClause +
		` ORDER BY ` + sortCol + ` ` + sortDir + `, id DESC`
	selectArgs := append([]any{}, cfg.Args...)
	if cfg.Limit > 0 {
		selectQ += ` LIMIT ?`
		selectArgs = append(selectArgs, cfg.Limit)
	}
	if cfg.Offset > 0 {
		selectQ += ` OFFSET ?`
		selectArgs = append(selectArgs, cfg.Offset)
	}

	return &pagedQueryResult{
		Total:    total,
		RowsSQL:  selectQ,
		RowsArgs: selectArgs,
	}, nil
}
