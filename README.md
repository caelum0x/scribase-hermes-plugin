# Scribase plugin for Hermes Agent

**Gives a [Hermes Agent](https://github.com/NousResearch/hermes-agent) a real hosted Postgres backend — provision a project, lint a migration before it runs, query the data, and spin up a disposable copy-on-write branch for one task — all against the live [Scribase](https://scribase.com) API, no human leaving the chat.**

Scribase is Postgres-as-a-service with a Supabase-API-compatible REST/Auth/
Storage/Realtime/Functions surface. This plugin is a thin, zero-dependency
client (stdlib `urllib` only) that calls only `api.scribase.com`.

▶️ **Demo video:** a 29s code-rendered terminal recreation of real captured
output (validator run, real lint-engine findings, two live production
`curl` calls) — see [`HACKATHON-SUBMISSION-2026-11-05.md`](./HACKATHON-SUBMISSION-2026-11-05.md)
in this repo for the full, honest breakdown of what's real-captured vs. what
a login-gated full agent loop couldn't show, and where the posted video will
be linked from once it's live on X.

## What it does

Registers five tools, no hooks, no middleware, no CLI/slash commands:

### `scribase_create_project`

1. Creates (or confirms) a project inside an existing Scribase organization.
2. Creates the project's first environment (`production` by default).
3. Polls until the environment finishes provisioning (bounded: it returns a
   `"status": "provisioning"` result with the operation id instead of
   hanging forever if it isn't ready yet — see "Disclosure" below).
4. Returns the new environment's Postgres connection URI and its API keys
   (`anon_key`, `service_role_key`, `publishable_key`, `secret_key`,
   `api_url`).

**Example call:**
```json
{"organization_id": "acme", "project_id": "store"}
```
**Example response:**
```json
{
  "organization_id": "acme", "project_id": "store", "environment_id": "production",
  "region": "eu-frankfurt", "status": "ready",
  "api_url": "https://store.api.scribase.com", "anon_key": "sb_anon_...",
  "publishable_key": "sb_publishable_...", "service_role_key": "sb_secret_...",
  "secret_key": "sb_secret_...", "connection_uri": "postgresql://postgres:...@db.store.scribase.com:5432/postgres"
}
```

### `scribase_lint_migration`

Submits a migration's `up` SQL to Scribase's real migration-safety linter —
the same engine the control plane's migration runner enforces, not a
generic prompt pattern-matching on text. It parses the SQL into a schema
model and checks it against real rules: a table created without row level
security, a `GRANT` to `PUBLIC`, a policy using `USING (true)`, a write
policy with no `WITH CHECK`, and a `SECURITY DEFINER` function are all
**block** findings; a foreign key with no supporting index is a **warn**
finding. The request always sends `"apply": false` — hardcoded in this
plugin, not read from the model's arguments — so this tool can never run
the migration, only check it.

**Example call:**
```json
{
  "organization_id": "acme", "project_id": "store", "environment_id": "production",
  "up": "create table public.payments (id uuid primary key, amount numeric not null);"
}
```
**Example response:**
```json
{
  "status": "blocked", "safe_to_apply": false,
  "blocking_findings": [
    {"rule": "missing_rls", "severity": "BLOCK", "subject": "public.payments",
     "line": 1, "message": "table has no row level security policy"}
  ],
  "warning_findings": [], "plan": {"steps": ["create table public.payments (...);"]}
}
```

### `scribase_query`

Runs a single read-only statement (`SELECT`/`WITH`/`TABLE`/`VALUES`/`SHOW`/
`EXPLAIN`) against a project's database and returns the rows (capped at
1000, default 100, with the true `row_count` reported so truncation is
visible). The control plane enforces read-only in two independent layers —
a static keyword check, then a Postgres `READ ONLY` transaction with a
bounded statement timeout — so a write or DDL statement, or a
data-modifying CTE, is rejected by the server itself, not by a check this
plugin invented.

**Example call:**
```json
{
  "organization_id": "acme", "project_id": "store", "environment_id": "production",
  "query": "select count(*) from public.payments", "limit": 10
}
```
**Example response:**
```json
{
  "kind": "rows", "row_count": 1, "returned": 1, "applied_limit": 10,
  "truncated": false, "rows": [{"count": 1842}]
}
```

### `scribase_branch_task`

Gives an agent a real, throwaway, **copy-on-write** Postgres branch for one
task — the kind of workflow a prompt or skill genuinely cannot do on its
own, because it needs real infrastructure (an actual forked database, a
real merge-base diff, a real teardown), not just careful instructions.
One tool, three actions:

- **`create`** — forks a new environment from an existing one (default
  `production`) in seconds. Use it before a risky migration, an
  exploratory query session, or anything you don't want touching the real
  database. The branch always carries a bounded TTL (1-24h, default 4h) so
  it self-deletes even if nothing ever calls `discard`, and lands in
  Scribase's own agent-branch slot pool instead of competing with a human's
  preview environments.
- **`promote`** — three-way merges the branch's schema changes back into
  its parent. The control plane itself refuses the merge if there are
  unresolved conflicts, unless `force: true` — and it refuses *that* too on
  an MFA-protected organization, since a forced merge needs an interactive
  step-up code this tool has no way to answer. Either way the real server
  decision comes back verbatim, not something this plugin invented.
- **`discard`** — deletes the branch immediately instead of waiting for
  its TTL. Permanent, matching the real endpoint's own contract.

**Example call (create):**
```json
{
  "action": "create", "organization_id": "acme", "project_id": "store",
  "base_environment_id": "production", "ttl_hours": 2
}
```
**Example response:**
```json
{
  "organization_id": "acme", "project_id": "store", "environment_id": "agent-7f3a9c21",
  "base_environment_id": "production", "data_mode": "snapshot", "ttl_hours": 2,
  "region": "eu-frankfurt", "status": "ready",
  "connection_uri": "postgresql://postgres:...@db.agent-7f3a9c21.scribase.com:5432/postgres",
  "api_url": "...", "anon_key": "...", "service_role_key": "...",
  "next_step": "When the task is done, call this tool again with action='promote' to merge this branch's schema back into 'production', or action='discard' to delete it immediately. Otherwise it self-deletes in 2h."
}
```
**Example call (promote, after the branch's migration ran clean):**
```json
{"action": "promote", "organization_id": "acme", "project_id": "store", "environment_id": "agent-7f3a9c21"}
```
**Example response:**
```json
{
  "status": "merged", "base_environment_id": "production", "environment_id": "agent-7f3a9c21",
  "applied": true, "dry_run": false, "clean": true,
  "changes": [{"object": "public.payments", "action": "added", "statement": "create table public.payments (...);"}],
  "conflicts": [], "statements": ["create table public.payments (...);"],
  "fork_base_trusted": true, "fork_base_origin": "fork"
}
```

### `scribase_memory_task`

Real, persistent memory for the agent — backed by a Postgres table in the
user's own Scribase project, not the model's own context window. One tool,
four actions: `store`, `recall`, `search`, `forget`. The backing table
(`public.hermes_agent_memories`, row-level security enabled) is created
automatically the first time `store` is called in a project; nothing needs
to be set up by hand first. An optional `scope` namespaces memories (one
scope per end user or per conversation) so more than one can share a
project without reading each other's.

`store`/`forget` are the only two actions that write, and both go through
`POST .../database/execute` — the real write-mode SQL route the Scribase
Studio SQL editor itself uses in "write mode" (confirmed against the
compiled control plane's source, `adapters/sql_execute.rs`), not the
read-only `database/query` route `scribase_query` and `recall`/`search`
use. Every value this tool interpolates into SQL — `content`, `metadata`,
`scope`, `memory_id` — is escaped with the standard Postgres
string-literal escape (doubled single quotes) before it is ever placed in
a statement; the model never gets to pass raw SQL through this tool (that
is what `scribase_query` is for, and it is read-only).

**Example call (store):**
```json
{
  "action": "store", "organization_id": "acme", "project_id": "store",
  "scope": "user-42", "content": "prefers dark mode and terse replies",
  "metadata": {"kind": "preference"}
}
```
**Example response:**
```json
{"status": "stored", "scope": "user-42", "memory_id": "4a2c5a00-5f0a-43d9-9337-edd894ca4293", "created_at": "2026-11-06T15:08:53.273144+00:00"}
```
**Example call (search):**
```json
{"action": "search", "organization_id": "acme", "project_id": "store", "scope": "user-42", "query": "dark mode"}
```
**Example response:**
```json
{"status": "ok", "scope": "user-42", "memories": [{"id": "4a2c5a00-...", "content": "prefers dark mode and terse replies", "metadata": {"kind": "preference"}, "created_at": "2026-11-06T15:08:53.273144+00:00"}], "row_count": 1, "truncated": false}
```

Verified live end to end against a real, temporary, no-login Scribase
project on production `api.scribase.com` on 2026-11-06 — store (x2),
recall, search, scope isolation (a second, never-used scope correctly
returns zero rows), and forget (deletes exactly the one memory, leaves the
other) — see `HACKATHON-SUBMISSION-2026-11-05.md`'s 2026-11-06 section for
the full real request/response transcript.

## Setup

1. Have a Scribase account and organization (`scribase.com`).
2. Create an organization API key: console → **Organization → API tokens**,
   or `POST /v1/organizations/{org}/api-keys` against the [Scribase Control
   API](https://docs.scribase.com/docs/api).
3. Install the plugin and set `SCRIBASE_API_KEY` when Hermes prompts for it
   (or add it to your Hermes profile's `.env`).

```bash
hermes plugins install scribase
```

### Optional: self-hosted Scribase

If you run your own Scribase cluster instead of the hosted
`api.scribase.com`, set the plugin's `api_base_url` config key to your
gateway's base URL (e.g. `https://api.your-domain.com`). This is a plain
URL, not a secret.

## Disclosure (Hermes plugin-catalog rule 13)

- **Hermes surfaces used:** `ctx.register_tool` only. No hooks, no
  middleware, no CLI/slash commands, no runtime overrides of Hermes
  internals.
- **Network calls:** only to the Scribase management API
  (`https://api.scribase.com` by default, or the operator's own
  `api_base_url` for a self-hosted cluster). No other host is contacted and
  no telemetry is sent anywhere.
- **Credentials:** the plugin stores no credentials of its own. It reads
  `SCRIBASE_API_KEY` exclusively through Hermes's secret scope
  (`agent.secret_scope.get_secret`), never from `os.environ` directly, a
  `.env` file, or any other local store.
- **Side effects:**
  - `scribase_create_project` creates real, billable resources in the
    user's Scribase organization (a project and a Postgres environment). It
    does not delete, suspend, or modify anything that already exists.
  - `scribase_lint_migration` has no side effects: `apply` is always sent
    as `false`, so the control plane only ever parses and lints the
    submitted SQL — it never opens a session against the tenant database.
  - `scribase_query` only ever runs inside a Postgres `READ ONLY`
    transaction the server opens; the server also statically rejects any
    write/DDL keyword before the statement is sent. Neither layer is
    something this plugin implements — both are enforced by the control
    plane itself.
  - `scribase_branch_task` with `action="create"` creates another real,
    billable environment (a copy-on-write branch), same disclosure as
    `scribase_create_project` — including that its connection string and
    API keys are returned into the conversation. `action="promote"` is the
    only action in this plugin that can change an *existing* environment
    (the parent): it applies a real schema merge, but only when the control
    plane's own three-way merge plan is conflict-free, or when `force` is
    set *and* the organization has no MFA factor (an MFA-protected
    organization's API key cannot satisfy the step-up challenge a forced
    merge requires, and the server rejects it outright rather than this
    plugin silently skipping the check). `action="discard"` permanently
    deletes the branch and its data.
  - `scribase_memory_task` with `action="store"` creates a new table
    (`hermes_agent_memories`) in the project the first time it is called
    there, and inserts one row per call thereafter. `action="forget"`
    deletes exactly one row by id. `action="recall"`/`action="search"` only
    read. No action in this tool can touch any table other than
    `hermes_agent_memories`, and `forget` can only ever delete the single
    row whose id is passed in — there is no action that deletes an entire
    scope or table.
- **Long-running behavior:** `scribase_create_project` and
  `scribase_branch_task` (`create`/`discard`) block for up to roughly 24-30
  seconds while polling the underlying operation. If it is not done by
  then, they return a `"status": "provisioning"`/`"discarding"` result
  with the operation id instead of blocking indefinitely, so neither can
  hang an unattended run (cron, messaging gateway).
- **No UI:** this is a pure tool-call plugin. No screens, no Desktop
  surface.
- **No self-updating code:** the plugin does not fetch or replace its own
  files. Updates reach users only through a new pinned commit in the
  Hermes plugin catalog.

## Dependencies

None beyond the Python standard library (`urllib`, `json`, `uuid`, `time`).

## License

MIT — see [LICENSE](./LICENSE).
