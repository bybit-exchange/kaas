# kb-ai — KaaS AI Engine

KaaS 的 Python AI 引擎：4 阶段 LLM 编译管线
(**Extract → Classify → Write → Index**)、LLM 迭代检索编译后的 wiki、流式
RAG 对话。以长驻 daemon 进程运行，通过 stdin/stdout JSON-line 协议与 Go 后端
通信；同时提供 MCP server 和若干一次性 CLI 命令。

## 安装

```bash
uv sync
```

## 运行 daemon

```bash
uv run kb-ai daemon
```

daemon 就绪后向 stderr 输出 `__READY__`，随后在 stdin 上接收 JSON-line 请求。

### JSON-line 协议

**请求** (每行一个 JSON 对象写入 stdin):

```json
{"id": "1", "cmd": "ping"}
{"id": "2", "cmd": "init", "payload": {"llm": {"api_key": "...", "base_url": "...", "model": "..."}}}
{"id": "3", "cmd": "shutdown"}
```

**响应** (每行一个 JSON 对象输出至 stdout):

```json
{"id": "1", "ok": true, "data": {"uptime_sec": 0.01}}
{"id": "1", "ok": false, "error": {"code": "UNKNOWN_CMD", "message": "..."}}
```

**流式响应** (streaming commands: `chat`, `pipeline-stream`):

```json
{"id": "3", "stream": true, "event": {...}}
{"id": "3", "stream": true, "event": {...}, "final": true}
```

### 支持的命令

| 命令 | 用途 |
|------|------|
| `ping` | 存活检查，返回 uptime |
| `init` | 初始化 OpenAI client (api_key / base_url / model) |
| `shutdown` | 优雅关闭 |
| `extract` | 从原始内容中提取知识 |
| `pipeline` | 运行 classify → write 管线 |
| `pipeline-stream` | 同上，流式输出 per-article SSE 事件 |
| `rewrite` | 改写 query 以优化检索 |
| `suggest` | 生成后续问题建议 |
| `index` | 重建 markdown 索引 (master-index / topic-index) + people stubs |
| `chat` | 流式 RAG 对话（含 citations） |
| `fetch-url` | 抓取 URL 并提取可读内容 |
| `cancel` | 取消正在进行的流式请求 |
| `derive` | Derive a topic-scoped KB from the article catalog into `derived/<slug>/` |

## MCP Server

```bash
# stdio 模式（默认，客户端直接 spawn）
uv run kb-ai mcp

# streamable-http 模式
uv run kb-ai mcp --http --host 127.0.0.1 --port 8082
```

提供一个 `ask` tool：对编译后的 KaaS wiki 进行 LLM 迭代检索 + 回答，返回
带引用的 markdown。

Signature: `ask(query, paths?, model?, kb?)`. `kb` selects a derived,
topic-scoped knowledge base by slug (see `kb-ai derive`); omit it to search the
whole wiki. An unknown slug is rejected rather than silently falling back to the
full wiki.

| 参数 | 说明 |
|------|------|
| `--stdio` | stdio 传输（默认） |
| `--http` | streamable-http 传输 |
| `--host` | HTTP 监听地址 (默认 `127.0.0.1`) |
| `--port` | HTTP 端口 (默认 `8082`) |
| `--kb-dir` | 覆盖知识库目录 |

HTTP 模式下设置 `KAAS_MCP_TOKEN` 环境变量可启用 Bearer 认证。

## CLI 命令

```bash
uv run kb-ai compile       # 从 stdin 读入 JSON，运行完整编译管线
uv run kb-ai fetch-url     # 从 stdin 读入 JSON，抓取 URL 转 markdown
uv run kb-ai chat          # 从 stdin 读入 JSON，执行 RAG 对话
uv run kb-ai rewrite       # 从 stdin 读入 JSON，改写检索 query
uv run kb-ai distill <paths...> [--kb .kaas]  # 将文件/目录摄入 KB 并编译
uv run kb-ai derive <topic> [--kb .kaas] [--slug s] [--force] [--model m] [--yes]
```

每个命令（distill / derive 除外）从 stdin 读取 JSON 请求，输出
`{"ok": ..., "data"|"error": ...}` 至 stdout。

`derive` builds a topic-scoped knowledge base at `<kb>/derived/<slug>/` from the
source KB's article catalog, leaving the source KB untouched. It prompts before
compiling unless `--yes` is given, and prints the resolved document count and the
run's cost. `--force` replaces an existing `derived/<slug>/` from a previous run.

## 环境变量

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `LLM_BASE_URL` / `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 LLM 端点 |
| `LLM_API_KEY` / `OPENAI_API_KEY` | — | LLM 端点 API key |
| `LLM_MODEL` | — | 默认模型名称 |
| `LLM_SUMMARIZE_MODEL` | — | 摘要阶段使用的模型 |
| `KAAS_PROMPTS_DIR` | 内置 `prompts/defaults/` | 自定义 prompt 模板目录 |
| `KB_AI_MAX_PROMPT_CHARS` | `80000` | prompt 最大字符数（超出则截断） |
| `KB_AI_PRICING` | — | JSON object of `{model: {"input": per-1M-USD, "output": per-1M-USD}}`. Prices models the built-in table lacks; unpriced models report 0.00 USD and warn once. Example: `{"gpt-4o": {"input": 2.5, "output": 10.0}}` |
| `KB_WORKERS` | `16` | 编译管线 worker 并发数。Read at two levels: `kb-ai compile`'s document pool and, in both routes, each phase's per-chunk fan-out (`core/extract.py`). A document over 16,000 chars splits, so the concurrent-call ceiling is documents x chunk workers — 12 x 16 = 192 for the queue route, which takes its document count from `worker.extract_workers` and reads this only for the fan-out. A ceiling, not a typical load: the fan-out is `min(chunks, KB_WORKERS)` and a 108-document reference corpus averaged 2.8 chunks. |
| `KAAS_DAEMON_MAX_WORKERS` | `8` | daemon 线程池大小。The 8 applies to a standalone `kb-ai daemon`; when the Go backend spawns it, `ai.daemon.concurrency` is passed here instead (16 by default, and refused at startup if below `worker.extract_workers`). |
| `KAAS_KB_DIR` | `./data` | MCP server 知识库根目录 |
| `KAAS_MCP_TOKEN` | — | MCP HTTP 模式 Bearer token |

## Prompts

Prompt 模板位于 `src/kb_ai/prompts/defaults/`，支持 `.md`（纯文本）和
`.yaml`（结构化）格式。编辑原文件或将 `KAAS_PROMPTS_DIR` 指向自定义目录即可
覆盖行为。

## 测试

```bash
uv run pytest tests/ -v
```
