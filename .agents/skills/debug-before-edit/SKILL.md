---
name: debug-before-edit
description: Use before changing code for runtime failures, configuration problems, Elasticsearch, Docker, Celery, database, or API defects. Requires reproduction and root-cause evidence first.
---

# Debug Before Edit

## Rule

Do not fix a problem that has not been reproduced or traced to a specific failing boundary.

## Investigation sequence

1. Preserve the current working tree:
   - `git status --short`
   - `git diff --stat`
2. Reproduce the failure with the smallest command or request.
3. Capture:
   - exact endpoint or command;
   - status code;
   - relevant log lines;
   - active configuration source;
   - container or process actually serving the request.
4. Trace the call path from router or task to service, repository, external client, and data source.
5. Compare the failing path with one working path in the same repository.
6. State one primary root-cause hypothesis and the evidence supporting it.
7. Test that hypothesis with a read-only probe before editing.

## External systems

For Elasticsearch, databases, Redis, Docker, or Celery:

- verify the active runtime configuration, not only `.env`;
- distinguish connection, authentication, authorization, index/table existence, mapping/schema, empty data, and parsing failures;
- redact credentials and authorization headers;
- use read-only probes first;
- do not rebuild infrastructure to work around an application defect.

## Fix

Apply one minimal fix at the boundary where the mismatch originates.

Do not:

- add broad fallback behavior before identifying the failure;
- return fake data;
- swallow exceptions silently;
- rewrite all callers when an adapter can preserve them;
- create a second client stack unless the existing one cannot be extended safely.

## Verification

Re-run the original reproduction first. Then test one adjacent success path and one expected failure path.
