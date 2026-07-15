---
name: verify-before-done
description: Use immediately before declaring a backend task complete. Requires fresh evidence from tests, runtime checks, APIs, logs, Docker, and the final diff.
---

# Verify Before Done

## Principle

Code inspection is not proof. Use fresh command output from the current working tree.

## Verification order

1. Re-run the exact defect reproduction or requested workflow.
2. Run the narrowest relevant tests.
3. Run lint or type checks only for changed files or the affected module unless repository rules require more.
4. Validate database migration or configuration reads when applicable.
5. Call the changed API with valid authentication when applicable.
6. Check the related background worker or scheduled task when applicable.
7. Check service and container state.
8. Inspect recent logs for new errors.
9. Review:
   - `git status --short`
   - `git diff --stat`
   - `git diff --check`
   - the complete task-related diff.

## Required completion evidence

Report:

- commands executed;
- pass/fail result;
- key API status and response shape;
- migration/configuration result with secrets masked;
- service/container status;
- modified files;
- remaining real limitations.

## Prohibited completion claims

Do not say complete, fixed, working, safe, or compatible when:

- the relevant command was not run;
- tests are stale;
- the service was not restarted when restart was required;
- only mocks were tested for an integration failure;
- a failing test was skipped or weakened;
- unrelated regressions remain unexplained;
- credentials appear in the diff or logs.

If full verification is blocked, state exactly what was verified, what was not, and why.
