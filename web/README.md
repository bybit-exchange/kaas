# KaaS Web UI

The front-end for KaaS — a single-user knowledge-as-a-service platform.

## Pages

| Page | Path | Description |
|------|------|-------------|
| **Chat** | `/chat/:sessionId?` | SSE streaming Q&A with source citations, multi-session state persistence |
| **Submit** | `/submit` | Paste text, upload files, or provide URLs for knowledge ingestion |
| **Wiki** | `/wiki/*` | Rendered Markdown articles with TOC and sidebar keyword search |
| **Status** | `/tasks` | Task polling table with detail dialog |

No auth — single-user local deploy only.

## Tech Stack

- **React 18** + TypeScript
- **Vite** (build + dev server)
- **Tailwind CSS** + shadcn/ui (Radix primitives)
- **Zustand** (chat session state management)
- **React Router** (client-side routing)
- **Vitest** + Testing Library (unit tests)

## Project Structure

```
src/
├── pages/          — Page components (Chat, Submit, Wiki, Tasks)
├── features/
│   ├── chat/       — MessageList, MessageInput, MarkdownRenderer, StreamHandler
│   └── wiki/       — WikiRenderer, sidebar, search
├── store/          — Zustand stores (chat sessions, preferences)
├── api/            — Backend API clients
├── components/     — Shared UI components (shadcn/ui)
├── hooks/          — Shared hooks
└── App.tsx         — Router + layout
```

## Development

```bash
pnpm install
pnpm dev
```

The Vite dev server proxies `/api` → `http://localhost:8080`, so the Go backend must be running. Easiest way: run `make dev` from the project root (starts both backend and frontend).

## Build

```bash
pnpm build   # tsc --noEmit + vite build → dist/
```

The built `dist/` directory is served by the Go backend as static files (via `KAAS_WEB_DIR`). In Docker, this is handled automatically by the multi-stage build.

## Tests

```bash
pnpm test          # single run
pnpm test:watch    # watch mode
```

## Key Patterns

- **Chat state**: Multi-session state managed by Zustand store (`store/chat.ts`), persists messages/streaming state across session switches without data loss
- **Streaming**: SSE via `fetch` + `ReadableStream`, abort-controllable per session
- **Wiki links**: Internal wiki links in chat responses are intercepted for SPA navigation
- **Markdown**: `react-markdown` with syntax highlighting (highlight.js) and mermaid diagram support
