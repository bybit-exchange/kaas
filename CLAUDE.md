# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Behavioral Guidelines

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Critical Rules

- **Language policy (applies to ALL agents including subagents/parallel agents)**:
  - **English is the only working language of this repository.** KaaS is open source and accepts contributions worldwide, so a Chinese artifact is a wall for most of the people we want reviewing and extending this code. This covers conversation, technical documentation, inline comments and doc comments, TODO/FIXME notes, task and plan descriptions, commit messages, branch names, PR titles and descriptions, issue comments, release notes, source identifiers, log messages, error strings, and LLM-facing prompts.
  - **Only exception — translation resources**: localized copies (`README.zh-CN.md`, `docs/assets/*.zh.svg`) and UI locale data (the `zh` maps in `web/src/i18n/strings.ts`). Keep them in sync with their English original; never let them become the source of truth. Everything *around* them — keys, comments, commit messages — is still English.
  - **Subagent enforcement**: When spawning any agent (Agent tool, parallel agents, worktree agents), the prompt to the agent MUST include the instruction: "Write everything in English — your replies, documentation, code comments, commit messages and PR text. The only exception is a file explicitly named as a translation, such as README.zh-CN.md." This ensures delegated work also follows the policy regardless of whether the subagent inherits this file.
- Always use the /table-design skill for table schema design and migration SQL creation
- When running Playwright E2E tests locally, use the `/faker` page and `dev-user` to bypass user authentication
