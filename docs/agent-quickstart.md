# KaaS — Agent Bootstrap Guide

You are an AI coding agent. A user asked you to set up or use KaaS, or simply
handed you this repository. Pick the path that matches what they asked for and
follow it **in order**. Stop and ask the user where indicated.

| The user wants | Follow |
|---|---|
| A wiki built from their files, queryable from your session | [Path 1](#path-1-build-a-wiki-and-query-it-yourself) |
| The full service, web UI included | [Path 2](#path-2-run-the-full-service) |
| To query a KaaS that already exists | [Path 3](#path-3-query-an-existing-kaas) |

If the request was vague, ask which one before installing anything. Path 1 is the
best default: nothing has to stay running, and you can query the result yourself.

---

## Path 1: build a wiki and query it yourself

### 1. Install `kb-ai`

Try these in order until one succeeds:

```bash
uv tool install "git+https://github.com/bybit-exchange/kaas.git#subdirectory=py"
```
```bash
pipx install "git+https://github.com/bybit-exchange/kaas.git#subdirectory=py"
```
```bash
pip install "git+https://github.com/bybit-exchange/kaas.git#subdirectory=py"
```

Verify: `kb-ai` is on PATH.

### 2. Ensure LLM credentials

Check the environment for `LLM_API_KEY` or `OPENAI_API_KEY`. If neither is
set, **ask the user** for an API key, and optionally a base URL and model.
Export them before running `kb-ai`:

```bash
export LLM_API_KEY=...          # required
export LLM_BASE_URL=...         # optional (defaults to OpenAI)
export LLM_MODEL=...            # model for your endpoint (defaults to gpt-4o-mini)
```

Do NOT proceed without a key.

### 3. Ask the user which sources to distill

**Stop and ask:**

> Do you want to distill just the current directory, or add other sources?
> - just this directory
> - other local directories (give paths)
> - URLs (I'll fetch them)
> - text you paste

For URLs, extract each page's readable markdown (kb-ai uses trafilatura to pull the article content, which lives in the JSON envelope's `data.content`):

```bash
echo '{"url":"https://example.com/page"}' | kb-ai fetch-url \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['data']['content'])" \
  > /tmp/page.md
```

Save pasted text to a `.md` file. Collect all local paths (the current dir,
extra dirs, and any files you created from URLs/pasted text).

### 4. Distill

```bash
kb-ai distill <path> [<path2> ...] --kb ./.kaas
```

This wraps readable text files into the KB's `raw/`, compiles them into a
wiki, and prints a JSON summary (`ingested`, `skipped`, `compile`). Report
the skipped files to the user (binaries/PDFs are not converted in this flow).

A knowledge base has four layers on disk: `raw/` (what came in), `extraction/`
(what we understood about each document, one file per raw document at the same
relative path), `wiki/` (what we composed) and `index/` (how to find it).

Pass `--extract-only` to run the extraction phase and stop — the wiki is left
alone. That is the loop for tuning an extract prompt: re-extract, read the new
`extraction/*.md` files in an editor, then compile for real.

The first run also freezes the article taxonomy into `<kb>/kaas.json`, so later
runs keep filing articles under the same categories even if the built-in
defaults change. To choose a different set, pass it on that first run:

```bash
kb-ai distill <path> --kb ./.kaas --categories concept,guide,reference
```

Passing a set that disagrees with an already-frozen one is honoured but warns,
because the result is a KB with two taxonomies in it.

### 4b. Check a knowledge base without spending anything

```bash
kb-ai check --kb ./.kaas
```

Reads four things and writes nothing: whether every document's extraction still
matches the document beside it, whether the parent has moved since a derived KB
was built (`unknown` for a KB that was not derived), how far the wiki is behind
the prompts that produced it, and whether any article names something that
appears in none of its sources. Safe to point at a read-only KB or someone else's.

Each list in the JSON is cut to 20 items by default, because on a 1024-document
knowledge base the full payload ran to 482KB and buried the four lines that
mattered. Nothing is lost to the cut: every list reports the `count` it was cut
from and sets `truncated`, and the stderr summaries always speak for the whole
set. Pass `--limit 0` for every row, or `--limit N` for a different slice — worth
doing when the lists you care about are the actionable ones (`mismatched`,
`unsourced`), since they are capped at the same 20 as the benign ones.

The lag half is what a `compile` cannot tell you: editing a write prompt changes
no document, so the next compile finds nothing to do and reports nothing. The
counts are report-only — re-composing an article adds to it rather than replacing
it, so a prompt edit is never a reason to pay the write phase again on its own.

The grounding half looks for the failure in issue #42: an article stating a config
field that no extraction behind it mentions. Each finding names the article, the
name, and the line it sits on, so you can judge it in place. It reads only table
rows and list items, and only names written as code spans or shaped like
identifiers — so a name is worth looking at, but a quiet report is weak evidence
rather than a clean bill.

Expect findings on a knowledge base compiled before the extract prompt learned to
carry enumerations: an identifier the extraction dropped is reported the same way
as one the write phase invented, and the fix for both is a re-extract. Articles
appear under `skipped` when an extraction they name is missing or was written
before `schema_version: 2` — a KB that has not been re-extracted since skips every
article, and the summary says so instead of reporting zero findings.

### 5. Wire up MCP so later sessions can query

**Claude Code:**
```bash
claude mcp add kaas -- env KAAS_KB_DIR=$(pwd)/.kaas LLM_API_KEY=$LLM_API_KEY kb-ai mcp
```

**Codex / openclaw:** add a stdio MCP server with command `kb-ai mcp` and env
`KAAS_KB_DIR=<abs path to .kaas>` plus `LLM_API_KEY` (and `LLM_BASE_URL` /
`LLM_MODEL` if used).

### 6. Close out

Tell the user:

> Done. Open a new agent session and just ask questions about the content you
> distilled — I'll answer from the KaaS wiki via the `ask` tool.

---

## Path 2: run the full service

Use this when the user wants the web UI, the REST API, or a KaaS that other
people can reach. It is a long-running server, so confirm the user actually wants
something left running before you start it.

### 1. Install the binary

```bash
curl -fsSL https://raw.githubusercontent.com/bybit-exchange/kaas/main/install.sh | sh
```

Linux amd64/arm64 and macOS arm64 only — there is no darwin/amd64 release, so on
an Intel Mac this fails at the download. Use the container below, or Path 1, there.
The release unpacks into `~/.local/share/kaas` and is symlinked as `~/.kaas/kaas`.

**`~/.kaas` is usually not on PATH**, so a bare `kaas serve` will fail right after
installing. Either export it first or invoke the absolute path:

```bash
export PATH="$HOME/.kaas:$PATH"
```

To uninstall later: `rm -rf ~/.local/share/kaas ~/.kaas/kaas`.

Prefer a container? `docker build -t kaas .` from a clone of this repository, then
run it with the same environment variables as below and `-p 8080:8080 -v
./data:/app/data`.

### 2. Ensure LLM credentials

Same as Path 1, step 2. Do NOT proceed without a key.

### 3. Start it

```bash
export LLM_API_KEY=...
kaas serve                      # listens on :8080
```

**Verify before you report success** — do not just check the process is alive:

```bash
curl -fsS http://localhost:8080/healthz
```

Then tell the user to open http://localhost:8080. They add content through the
Submit page; compile progress shows on the Tasks page and the result under Wiki.

### 4. Optional: let agents query it over HTTP

Only if the user wants remote agents to reach this instance. Restart the server
with the MCP endpoint enabled and a token set:

```bash
export KAAS_MCP_ENABLED=true
export KAAS_MCP_TOKEN=<a secret the user chooses>
kaas serve
```

Register it (see Path 3 for the client side), then confirm the token is required
rather than assuming it — a request without the header should be rejected.

---

## Path 3: query an existing KaaS

**Stop and ask** which of these the user has, since the transport differs:

**A knowledge-base directory on this machine** — a `.kaas` or `data` directory
with `wiki/` inside. Use stdio: no network surface, no token. Requires `kb-ai`
(Path 1, step 1):

```bash
claude mcp add kaas -- env KAAS_KB_DIR=<absolute path> LLM_API_KEY=$LLM_API_KEY kb-ai mcp
```

**A running KaaS server** — it must have been started with
`KAAS_MCP_ENABLED=true`, otherwise `/mcp` is not served:

```bash
claude mcp add --transport http kaas http://<host>:8080/mcp
```

If the user set `KAAS_MCP_TOKEN`, the client has to send
`Authorization: Bearer <token>`.

For Codex / openclaw, register the same command or URL through their own MCP
configuration.

Either way you get one tool: `ask(query, paths?, model?, kb?)`, which returns a
cited Markdown answer grounded in the wiki. Pass the citations back to the user
rather than paraphrasing them away — they point at real article paths the user
can open.

`kb` selects a derived, topic-scoped knowledge base by slug (see
`kb-ai derive`). Omit it to search the whole wiki. An unknown slug is an error,
not a silent fall back to the full wiki, so you never get an answer drawn from a
corpus you did not ask for.
