---
name: backend-minimal-change
description: Use for any change to this existing Python backend. Enforces narrow scope, reuse of current code, low code volume, and preservation of unrelated behavior.
---

# Backend Minimal Change

## Objective

Implement the smallest coherent change that solves the requested problem without introducing a parallel architecture.

## Before editing

1. Read the nearest `AGENTS.md`.
2. Run:
   - `git status --short`
   - `git diff --stat`
3. Identify the exact entry point, call chain, data model, and tests.
4. Search for existing clients, services, repositories, schemas, helpers, and configuration readers that already solve part of the task.
5. Write a short change map:
   - files that must change;
   - behavior changed in each file;
   - tests needed;
   - files deliberately not changed.

Do not create code until the current implementation and reuse points are identified.

## Change rules

- Modify an existing implementation before creating a parallel one.
- Do not introduce a new layer for a single call site.
- Do not create a helper used only once unless it isolates a dangerous side effect or improves testability materially.
- Do not rename, move, reformat, or clean unrelated files.
- Do not generate documentation unless requested.
- Do not replace a working module merely because another design looks cleaner.
- Prefer adapters at external-system boundaries over changes throughout business services.
- Preserve local uncommitted changes.
- Never use destructive Git cleanup commands.

## Scope budget

Treat either threshold as a warning:

- more than 8 modified files;
- more than 300 added production lines, excluding migrations and focused tests.

When a warning is reached:

1. stop adding abstractions;
2. search again for reusable code;
3. remove duplicated branches and wrappers;
4. explain why each remaining file is necessary before continuing.

The budget is not a target.

## Completion review

Inspect only the current diff and remove:

- duplicate logic;
- speculative extension points;
- one-use wrappers;
- unused imports and configuration;
- comments that restate code;
- fallback branches unsupported by a real requirement.

Then run the narrowest relevant tests.
