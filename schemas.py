"""Tool schemas for the Scribase Hermes plugin — this is what the LLM reads to
decide when and how to call each tool."""

SCRIBASE_CREATE_PROJECT = {
    "name": "scribase_create_project",
    "description": (
        "Provision a new hosted Postgres backend project on Scribase "
        "(api.scribase.com) and return its connection string and API keys. "
        "Creates the project, creates its first environment (production by "
        "default), waits for it to finish provisioning, then reads back the "
        "Postgres connection URI and the environment's anon/service-role API "
        "keys. Use this when a user wants a real Postgres database plus a "
        "REST/Auth/Storage/Realtime API for an app and doesn't want to set "
        "up a database by hand. Requires an existing Scribase organization "
        "id and an organization API key configured as SCRIBASE_API_KEY."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "organization_id": {
                "type": "string",
                "description": (
                    "The Scribase organization this project belongs to "
                    "(lowercase alphanumeric + hyphens, 2-64 chars). The "
                    "organization must already exist."
                ),
            },
            "project_id": {
                "type": "string",
                "description": (
                    "A new, unique project id within the organization "
                    "(lowercase alphanumeric + hyphens, 2-64 chars)."
                ),
            },
            "environment_id": {
                "type": "string",
                "description": "Name for the project's first environment. Defaults to 'production'.",
            },
            "region": {
                "type": "string",
                "description": "Region to provision in. Defaults to 'eu-frankfurt' (hosted Scribase's region).",
            },
            "postgres_major": {
                "type": "integer",
                "description": "Postgres major version. Only 17 is currently supported; defaults to 17.",
            },
        },
        "required": ["organization_id", "project_id"],
    },
}


SCRIBASE_LINT_MIGRATION = {
    "name": "scribase_lint_migration",
    "description": (
        "Check a SQL migration for safety against Scribase's real migration "
        "linter BEFORE running it — no generic prompt or skill can do this, "
        "because it requires parsing the SQL against actual Postgres lock and "
        "RLS semantics. Submits the migration's `up` SQL to Scribase's "
        "control plane (api.scribase.com), which builds a schema model from it "
        "and runs the same rule set the real migration runner enforces: a "
        "table created without row level security, a GRANT to PUBLIC, a "
        "policy using `USING (true)`, a write policy missing `WITH CHECK`, and "
        "a SECURITY DEFINER function are all 'block' findings; a foreign key "
        "left without a supporting index is a 'warn' finding. This call NEVER "
        "applies the migration — `apply` is always sent as false, so it is "
        "purely a dry-run safety check, not a mutation. Use this whenever a "
        "user or agent is about to hand a CREATE TABLE / ALTER TABLE / CREATE "
        "POLICY / GRANT statement to a Scribase project and wants to know "
        "whether it is safe first. Requires an existing Scribase organization, "
        "project and environment, and an organization API key configured as "
        "SCRIBASE_API_KEY."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "organization_id": {
                "type": "string",
                "description": "The Scribase organization the project belongs to.",
            },
            "project_id": {
                "type": "string",
                "description": "The existing Scribase project the migration targets.",
            },
            "environment_id": {
                "type": "string",
                "description": "The existing environment to lint against (e.g. 'production').",
            },
            "up": {
                "type": "string",
                "description": (
                    "The migration's forward SQL (the `CREATE TABLE`/`ALTER "
                    "TABLE`/`CREATE POLICY`/... statements to check). This is "
                    "never executed — only parsed and linted."
                ),
            },
            "down": {
                "type": "string",
                "description": "Optional rollback SQL, included for completeness; also never executed.",
            },
            "migration_name": {
                "type": "string",
                "description": "Optional descriptive name for the migration being checked.",
            },
        },
        "required": ["organization_id", "project_id", "environment_id", "up"],
    },
}


SCRIBASE_QUERY = {
    "name": "scribase_query",
    "description": (
        "Run a single read-only SQL statement (SELECT / WITH / TABLE / VALUES "
        "/ SHOW / EXPLAIN) against a Scribase project's Postgres database and "
        "return the rows. The statement is rejected if it is not read-only — "
        "both by a static keyword check before it is sent, and again by "
        "Postgres itself inside a `READ ONLY` transaction — so this can never "
        "write, alter, or drop anything, even a data-modifying CTE the static "
        "check missed. Results are capped (default 100 rows, max 1000) and "
        "`row_count` reports the true total so you know if the result was "
        "truncated. Use this to inspect data or debug a schema in an existing "
        "project. Requires an existing Scribase organization, project and "
        "environment, and an organization API key configured as "
        "SCRIBASE_API_KEY."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "organization_id": {
                "type": "string",
                "description": "The Scribase organization the project belongs to.",
            },
            "project_id": {
                "type": "string",
                "description": "The existing Scribase project to query.",
            },
            "environment_id": {
                "type": "string",
                "description": "The existing environment to query (e.g. 'production').",
            },
            "query": {
                "type": "string",
                "description": (
                    "A single read-only SQL statement: SELECT, WITH, TABLE, "
                    "VALUES, SHOW, or EXPLAIN (not EXPLAIN ANALYZE). Any "
                    "write or DDL statement is rejected before it reaches the "
                    "database."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max rows to return, 1-1000. Defaults to 100.",
            },
        },
        "required": ["organization_id", "project_id", "environment_id", "query"],
    },
}
