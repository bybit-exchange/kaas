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
  - **Chinese**: All human-readable output — conversation with user, technical documentation (CONTEXT.md, ADRs, READMEs, inline doc comments, PR descriptions), TODO/FIXME comments, and task/plan descriptions.
  - **English**: Source code identifiers, log messages, error strings, LLM-facing prompts/instructions (e.g. skill definitions, agent prompts), and **commit messages and branch names** — git history and refs are public artifacts of this repository.
  - **Subagent enforcement**: When spawning any agent (Agent tool, parallel agents, worktree agents), the prompt to the agent MUST include the instruction: "Reply to the user and write all documentation in Chinese. Write commit messages in English, subject and body. Keep source identifiers, log messages and error strings in English." This ensures delegated work also follows the policy regardless of whether the subagent inherits this file.
- Always use the /table-design skill for table schema design and migration SQL creation
- When running Playwright E2E tests locally, use the `/faker` page and `dev-user` to bypass user authentication
