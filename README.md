# Scribase plugin for Hermes Agent

Lets a [Hermes Agent](https://github.com/NousResearch/hermes-agent) run a
real hosted Postgres backend on [Scribase](https://scribase.com) — a
Postgres-as-a-service with a Supabase-API-compatible REST/Auth/Storage/
Realtime/Functions surface — without the user leaving the chat: provision a
project, check a migration for real safety problems before it runs, and
query the data, all against the live API.

## What it does

Registers three tools, no hooks, no middleware, no CLI/slash commands:

### `scribase_create_project`

1. Creates (or confirms) a project inside an existing Scribase organization.
2. Creates the project's first environment (`production` by default).
3. Polls until the environment finishes provisioning (bounded: it returns a
   `"status": "provisioning"` result with the operation id instead of
   hanging forever if it isn't ready yet — see "Disclosure" below).
4. Returns the new environment's Postgres connection URI and its API keys
   (`anon_key`, `service_role_key`, `publishable_key`, `secret_key`,
   `api_url`).

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
the migration, only check it. Returns `{status, safe_to_apply,
blocking_findings, warning_findings, plan}`.

### `scribase_query`

Runs a single read-only statement (`SELECT`/`WITH`/`TABLE`/`VALUES`/`SHOW`/
`EXPLAIN`) against a project's database and returns the rows (capped at
1000, default 100, with the true `row_count` reported so truncation is
visible). The control plane enforces read-only in two independent layers —
a static keyword check, then a Postgres `READ ONLY` transaction with a
bounded statement timeout — so a write or DDL statement, or a
data-modifying CTE, is rejected by the server itself, not by a check this
plugin invented.

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
- **Long-running behavior:** the tool call itself blocks for up to roughly
  30 seconds while polling the new environment's provisioning operation. If
  provisioning is not done by then, it returns a `"status": "provisioning"`
  result with the operation id instead of blocking indefinitely, so it
  cannot hang an unattended run (cron, messaging gateway).
- **No UI:** this is a pure tool-call plugin. No screens, no Desktop
  surface.
- **No self-updating code:** the plugin does not fetch or replace its own
  files. Updates reach users only through a new pinned commit in the
  Hermes plugin catalog.

## Dependencies

None beyond the Python standard library (`urllib`, `json`, `uuid`, `time`).

## License

MIT — see [LICENSE](./LICENSE).
