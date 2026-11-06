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


SCRIBASE_BRANCH_TASK = {
    "name": "scribase_branch_task",
    "description": (
        "Give an agent a throwaway, real copy-on-write Postgres branch for one "
        "task — no generic prompt or skill can do this, because it requires "
        "real infrastructure, not just careful instructions. action='create' "
        "forks a brand-new environment from an existing one (default "
        "'production') in seconds, so the agent can test a risky migration, "
        "run exploratory queries, or try something destructive against real "
        "data without any chance of touching the real database. When the task "
        "is done, call this again with action='promote' to three-way merge "
        "the branch's schema changes back into its parent (the control plane "
        "refuses the merge if there are unresolved conflicts, unless "
        "force=true — which itself is refused for an MFA-protected "
        "organization, since a forced merge needs an interactive step-up this "
        "tool cannot answer), or action='discard' to delete the branch outright "
        "when the task failed or was just exploration. A branch always carries "
        "a short TTL (default 4h, max 24h) and self-deletes even if nothing "
        "ever calls discard. Requires an existing Scribase organization and "
        "project, and an organization API key configured as SCRIBASE_API_KEY."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "promote", "discard"],
                "description": (
                    "'create' cuts a new branch. 'promote' merges an existing "
                    "branch's schema back into its parent. 'discard' deletes "
                    "an existing branch immediately instead of waiting for its "
                    "TTL."
                ),
            },
            "organization_id": {
                "type": "string",
                "description": "The Scribase organization the project belongs to.",
            },
            "project_id": {
                "type": "string",
                "description": "The existing Scribase project to branch within.",
            },
            "environment_id": {
                "type": "string",
                "description": (
                    "For action='create': an optional name for the new branch "
                    "(auto-generated like 'agent-ab12cd34' if omitted). For "
                    "action='promote' or action='discard': required — the "
                    "existing branch to act on."
                ),
            },
            "base_environment_id": {
                "type": "string",
                "description": (
                    "The parent environment. For action='create', the branch "
                    "forks from this (default 'production'). For "
                    "action='promote', the branch's schema is merged into this "
                    "(default 'production'); it must be the same environment "
                    "the branch was actually created from."
                ),
            },
            "data_mode": {
                "type": "string",
                "enum": ["snapshot", "sanitized", "schema_only"],
                "description": (
                    "Only used by action='create'. 'snapshot' clones the "
                    "parent's real data via copy-on-write (best for "
                    "reproducing a real bug or testing a migration against "
                    "real data). 'sanitized' clones it with sensitive columns "
                    "and secrets scrubbed. 'schema_only' copies just the "
                    "schema, no rows. Defaults to 'snapshot'."
                ),
            },
            "ttl_hours": {
                "type": "integer",
                "description": (
                    "Only used by action='create'. Hours until the branch "
                    "auto-deletes itself even if nothing calls discard. Must "
                    "be 1-24 (this keeps it in Scribase's dedicated "
                    "agent-branch slot pool instead of the human preview "
                    "pool). Defaults to 4."
                ),
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Only used by action='promote'. If true, the branch's "
                    "schema wins every conflict instead of the merge failing "
                    "on the first one. Refused by the server with "
                    "'mfa_required' for an organization that has multi-factor "
                    "authentication enabled, since a forced merge needs an "
                    "interactive step-up code. Defaults to false."
                ),
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Only used by action='promote'. If true, plans the merge "
                    "and reports its changes/conflicts without applying "
                    "anything. Defaults to false."
                ),
            },
        },
        "required": ["action", "organization_id", "project_id"],
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


SCRIBASE_MEMORY_TASK = {
    "name": "scribase_memory_task",
    "description": (
        "Give the agent real, persistent memory backed by a Postgres table "
        "in its own Scribase project — not the model's context window, a "
        "row that is still there in the next session, next week, on a "
        "different machine. action='store' saves one memory (free-text "
        "content plus an optional JSON metadata object) under a scope (an "
        "optional namespace — use one scope per end user or per "
        "conversation if more than one needs separate memories in the same "
        "project; defaults to 'default'). action='recall' lists the most "
        "recent memories in a scope, newest first. action='search' does the "
        "same but filtered to memories whose content contains a substring "
        "(case-insensitive). action='forget' deletes exactly one memory by "
        "the id a prior store returned — there is no 'forget everything' "
        "action, so one bad call can never wipe a whole scope. The backing "
        "table is created automatically (with row-level security enabled) "
        "the first time this is called with action='store' in a project; "
        "nothing needs to be set up by hand first. Requires an existing "
        "Scribase organization and project, and an organization API key "
        "configured as SCRIBASE_API_KEY."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["store", "recall", "search", "forget"],
                "description": (
                    "'store' saves a new memory. 'recall' lists the most "
                    "recent memories in a scope. 'search' filters by a "
                    "content substring. 'forget' deletes one memory by id."
                ),
            },
            "organization_id": {
                "type": "string",
                "description": "The Scribase organization the project belongs to.",
            },
            "project_id": {
                "type": "string",
                "description": "The existing Scribase project to store memories in.",
            },
            "environment_id": {
                "type": "string",
                "description": "The environment to store memories in. Defaults to 'production'.",
            },
            "scope": {
                "type": "string",
                "description": (
                    "An optional namespace so more than one agent/user/"
                    "conversation can keep separate memories in the same "
                    "project without reading each other's. Defaults to "
                    "'default'. Max 128 characters."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "Only used by action='store'. The memory's free text, "
                    "up to 8192 characters."
                ),
            },
            "metadata": {
                "type": "object",
                "description": (
                    "Only used by action='store'. An optional JSON object "
                    "of structured fields alongside the free text (e.g. "
                    "{\"kind\": \"preference\"})."
                ),
            },
            "memory_id": {
                "type": "string",
                "description": (
                    "Only used by action='forget'. The UUID a prior "
                    "action='store' call returned."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Only used by action='search'. A case-insensitive "
                    "substring to match against stored memories' content."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Only used by action='recall'/'search'. Max memories to "
                    "return, 1-200. Defaults to 20."
                ),
            },
        },
        "required": ["action", "organization_id", "project_id"],
    },
}
