---
name: safe-database-config
description: Use for database configuration writes, migrations, runtime settings, or Docker database operations. Prevents destructive changes and credential leakage.
---

# Safe Database Configuration

## Discover first

Before writing:

1. Identify the actual database engine and running container or process.
2. Identify the application's active database URL and runtime configuration source.
3. Read the existing ORM model, repository, configuration service, and migration conventions.
4. Check the current migration revision.
5. Back up only the rows or files affected by the task.

Do not infer the production database from filenames alone. A repository may contain SQLite files while the running application uses PostgreSQL or another database.

## Configuration changes

- Use the existing configuration model and service.
- Update only named target keys.
- Use transactions.
- Make scripts idempotent.
- Mark secrets sensitive using the repository's existing mechanism.
- Redact passwords, tokens, full connection strings, and authorization headers.
- Verify the new value by reading it through the application configuration layer.
- Do not rely solely on `.env` when runtime settings live in the database.

## Migrations

- Reuse existing tables when they fit the data and access pattern.
- Create a new table only after documenting why existing tables are insufficient.
- Follow current Alembic conventions.
- Provide a safe downgrade when feasible.
- Add only indexes required by demonstrated queries.
- Do not silently transform or delete unrelated rows.

## Forbidden actions

Never:

- run `docker compose down -v`;
- delete or recreate a Docker volume;
- drop or recreate the database;
- truncate business or configuration tables;
- clear Redis indiscriminately;
- overwrite all configuration rows;
- commit real credentials;
- print secret values in logs.

## Verification

Confirm:

- transaction committed;
- expected rows changed and no others;
- migration revision is correct;
- application reads the new configuration;
- dependent service starts;
- rollback behavior is understood.
