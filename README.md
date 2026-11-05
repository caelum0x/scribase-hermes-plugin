# Scribase plugin for Hermes Agent

Lets a [Hermes Agent](https://github.com/NousResearch/hermes-agent) provision
a real hosted Postgres backend on [Scribase](https://scribase.com) — a
Postgres-as-a-service with a Supabase-API-compatible REST/Auth/Storage/
Realtime/Functions surface — without the user leaving the chat.

## What it does

Registers one tool, `scribase_create_project`, that:

1. Creates (or confirms) a project inside an existing Scribase organization.
2. Creates the project's first environment (`production` by default).
3. Polls until the environment finishes provisioning (bounded: it returns a
   `"status": "provisioning"` result with the operation id instead of
   hanging forever if it isn't ready yet — see "Disclosure" below).
4. Returns the new environment's Postgres connection URI and its API keys
   (`anon_key`, `service_role_key`, `publishable_key`, `secret_key`,
   `api_url`).

That's it — no other tools, no hooks, no middleware, no CLI/slash commands.

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
- **Side effects:** calling the tool creates real, billable resources in
  the user's Scribase organization (a project and a Postgres environment).
  It does not delete, suspend, or modify anything that already exists.
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
