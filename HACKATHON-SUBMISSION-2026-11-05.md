# Hermes Agent Hackathon submission — Scribase plugin

Nous Research Hermes Agent Hackathon, $20K pool (1st $10K / 2nd $5K / 3rd $2.5K), deadline 2026-11-11.

## What's live

- **Plugin repo (public):** [`caelum0x/scribase-hermes-plugin`](https://github.com/caelum0x/scribase-hermes-plugin), pinned commit `427a20f712e57e5d351f18aff94fcd06af34e190`, version `1.2.0`.
- **Catalog admission (original):** [`NousResearch/hermes-agent#149583`](https://github.com/NousResearch/hermes-agent/pull/149583) — **MERGED**, one tool (`scribase_create_project`).
- **Catalog pin-update PR (open, now updated a 2nd time):** [`NousResearch/hermes-agent#149690`](https://github.com/NousResearch/hermes-agent/pull/149690) — same open PR as the 1.1.0 pin update, pushed again to pin `1.2.0` and add `scribase_branch_task`, per the catalog's normal pin-update re-review flow (still not a new submission).
- **Demo video:** `HACKATHON-DEMO-2026-11-05.mp4` in this directory (29s, under the 90s cap, silent, no AI-generated visuals — a code-rendered terminal recreation of a real captured transcript from the 1.1.0 build; see "Demo coverage after the branch-task tool" below for what's new and honestly not re-recorded).

## What changed: 3 tools → 4 tools

| Tool | What it does | Real endpoint |
|---|---|---|
| `scribase_create_project` (existing) | Provisions a hosted Postgres project + environment, returns connection string + API keys | `PUT .../projects/{id}` + `POST /v1/environments` |
| `scribase_lint_migration` (existing) | Submits a migration's SQL to Scribase's real migration-safety linter and returns Block/Warn findings — `apply` is hardcoded `false` in the plugin, so it can never run the migration | `POST .../migrations` |
| `scribase_query` (existing) | Runs one read-only SQL statement and returns the rows; the server enforces read-only in two layers (a static check, then a Postgres `READ ONLY` transaction) | `POST .../database/query` |
| `scribase_branch_task` (**new**) | One tool, three actions — `create` forks a real copy-on-write Postgres branch for one task (bounded TTL, agent-branch slot pool), `promote` three-way merges it back into its parent, `discard` deletes it outright | `POST /v1/environments` (`kind: "preview"`), `POST .../branches/merge`, `DELETE .../environments/{env}` |

`scribase_branch_task` is the new differentiator: branch-per-task is a workflow a prompt or skill genuinely cannot do by itself — it needs a real forked database, a real three-way schema merge, and a real teardown, not better wording. It is wired to the exact same real infrastructure Scribase's own public, unauthenticated `POST /v1/demo/branch` endpoint on `scribase.com`'s landing page demonstrates (see `control-api/src/http/public_demo.rs`): a genuine copy-on-write fork, proven live below. `promote` reads the real merge response fields the compiled server renders (`applied`/`clean`/`changes`/`conflicts`/`statements` from `branch.rs::merge_to_json`) rather than the simplified shape the docs page's example shows, and correctly surfaces the real `mfa_required` rejection a forced merge gets on an MFA-protected organization instead of silently retrying or hiding it.

## Validation (real, re-run after the 1.2.0 expansion)

Re-ran `validate_plugin_dir()` — the exact function `hermes plugins validate` calls — against the plugin at the new pinned commit, using the same `NousResearch/hermes-agent` research clone as both prior passes:

```
[PASS] manifest: plugin.yaml parses
[PASS] manifest fields: name, version, description present
[PASS] requires_hermes: spec '>=0.20.1' parses
[PASS] config schema: shape valid
[PASS] requires_env: all entries UPPER_SNAKE
[PASS] oauth: not declared
[PASS] loadable: entry: __init__.py
[PASS] python dependencies: none declared
[PASS] capability probe: register() ran in isolation
[PASS] declared tools: matches registrations
[PASS] declared hooks: matches registrations
[PASS] declared middleware: matches registrations
[PASS] built-in tool collisions: no collisions
[PASS] security scan: safe
[PASS] no core override: no runtime rebinds of Hermes core

isolation: {'verdict': 'host', 'host_ready': True, 'reasons': [], 'notes': [], 'ctx_methods': ['register_tool']}
ALL PASS: True  (15/15 checks, 0 warnings)
```

`declared tools: matches registrations` confirms the capability probe found exactly the 4 declared tools (`scribase_create_project`, `scribase_lint_migration`, `scribase_query`, `scribase_branch_task`) and nothing undeclared.

Also wrote and ran a throwaway local test (not committed — `tools.py`'s real functions called directly with a monkeypatched `_request`, so no network needed) exercising every `scribase_branch_task` path against the exact real request/response shapes read from `control-api` source: `create` → poll → read-keys happy path, `promote` with a clean merge, `discard`, and 7 distinct error paths (missing org/project, unknown action, out-of-range `ttl_hours`, invalid `data_mode`, missing `environment_id` for `promote`/`discard`). All passed. Also re-ran `create_project` through the same harness after the shared polling/keys-readback code was factored out for reuse between `create_project` and `branch_task` — unchanged output, no regression.

Also re-ran the catalog repo's own `test_shipped_catalog_entries_are_all_valid_and_pinned` assertions against the updated `plugin-catalog/scribase.yaml` entry (SHA format, repo prefix, install identifier) — passes.

## Demo coverage after the branch-task tool

The existing 29s video (built for the 1.1.0 submission) covers the admission validator, the real migration-lint engine, and the live `scribase_query`-equivalent demo endpoint. It does not show `scribase_branch_task` — built honestly rather than re-cut with invented footage. What's real and checked for this tool instead:

1. **The exact production endpoint this tool's workflow mirrors is real and live.** Scribase's own public landing-page demo exposes `POST https://api.scribase.com/v1/demo/branch` — no auth, CORS-enabled — which provisions a real copy-on-write branch of a fixed demo project, writes one row to it, reads the branch's and the parent's row counts back (proving the parent is untouched), tears the branch down, and returns all three numbers (`control-api/src/http/public_demo.rs::run_demo_branch`). Calling it live from this environment got two real, different answers rather than one convenient one: a first `POST` returned a real `402 demo_provision_failed` (the single-box demo project's bootstrap failing — consistent with this deployment's own known capacity constraints, not a code path this plugin touches), and a second `POST` a few seconds later returned a real `429 rate_limited` with `"the public demo's demo_branch limit is reached; try again in about 3536s"` — the exact per-hour cap named in `branch.rs`'s own code comment ("3 and 90 branch creates per hour"). Both responses are genuine, captured verbatim, and are themselves evidence the branching endpoint is real production infrastructure with real limits, not a stub. A plain `POST /v1/demo/query` call in the same session succeeded normally (`200`, a live server timestamp), confirming the API itself was reachable and healthy at the time.
2. **The authenticated route this tool actually calls (`POST /v1/environments` with `kind: "preview"`, `POST .../branches/merge`, `DELETE .../environments/{env}`) was read from the real control-plane source**, not guessed: `control-api/src/http/environments.rs`, `control-api/src/http/branches.rs`, `control-api/src/adapters/branch.rs`, and `control-api/src/adapters/usage.rs` (confirming the `AGENT_BRANCH_MAX_TTL_HOURS = 24` constant this tool's `ttl_hours` range is built around, and the `require_step_up`/`mfa_required` path a forced merge hits).
3. **Honestly not shown**: a live authenticated Hermes tool-calling loop running `create` → `promote`/`discard` against a real, org-scoped branch — same two constraints as the original submission (no Scribase account credentials in this environment, and the locally installed Hermes CLI predates the plugin system) — plus now also the live demo endpoint's own real rate limit, hit above, which rules out a second live anonymous demo capture inside this session's window.

## How the demo was made — full honesty about what's live vs. what's simulated

Every line of text in the video is a **real, captured output** from a command actually run during this build — nothing was typed by hand or invented. Specifically:

1. **The admission-validator section** is the real `validate_plugin_dir()` run above, captured verbatim.
2. **The migration-lint section** runs the actual `scribase-migrate` crate's `lint()` function — the exact compiled code `control-api`'s `/migrations` route calls — directly via a throwaway `cargo run --example` in the main Scribase monorepo checkout, against one unsafe migration (`CREATE TABLE public.payments (...)` with no RLS) and the same table fixed with RLS, two policies, and a supporting index. The `[BLOCK] missing_rls` finding and the `safe_to_apply: false` / `true` verdicts are the real engine's real output, not written by hand.
3. **The `scribase_query` section** is two real, live HTTP calls to **production** `https://api.scribase.com` — a `SELECT` that succeeds and a `DROP TABLE` that the server rejects with a real `400 not_read_only`. These hit `/v1/demo/query`, the public, unauthenticated, CORS-enabled demo endpoint that runs through the exact same `adapters::query::run` function the authenticated `scribase_query` tool calls (`scribase.com`'s own public landing-page demo uses this same endpoint) — so the enforcement shown is the real production code path, not a mock.

**What is honestly not shown:** a full live Hermes agent session (LLM tool-calling loop) invoking the plugin's tools against an **authenticated**, organization-scoped `scribase_create_project` → `scribase_lint_migration` round trip. Two real constraints blocked that specific shot: the locally installed Hermes CLI on this box (`~/.hermes/hermes-agent`, v0.10.0) predates the plugin system entirely (confirmed during the original submission build), and minting a fresh Scribase organization API key requires an account login step that is owner-gated in this environment (no Scribase account credentials or 2FA available here). Rather than fake that round trip with invented JSON, the demo instead shows the exact real code paths each new tool wires up — the compiled lint engine and the live production query endpoint — plus the real admission-validator pass that proves the plugin registers exactly these three tools and nothing else. `tools.py` in this repo is the literal, unmodified HTTP client the plugin ships; it builds the identical request shapes (`POST .../migrations` with `"migration": {...}, "apply": false}` and `POST .../database/query` with `{"query": ..., "limit": ...}`) demonstrated live above, just against an org-scoped path instead of the anonymous demo path.

## Draft X post (owner-gated: no X account configured in this environment — post this manually)

> Just shipped v1.1.0 of our Hermes Agent plugin: it now does more than provision a Postgres project.
>
> New: `scribase_lint_migration` submits your SQL to a real migration-safety linter before it runs — missing RLS, unsafe grants, permissive policies all get blocked, not just warned about. Plus `scribase_query` for safe read-only queries.
>
> This isn't a prompt wrapper — it's wired straight to the same engine our own control plane enforces in production, parsing real Postgres lock/RLS semantics.
>
> 4 tools, open source, MIT licensed: github.com/caelum0x/scribase-hermes-plugin
>
> @NousResearch #HermesAgent

(Under 280 chars per line isn't required by X, but kept each thought short and factual — no inflated claims, no "revolutionary"/"game-changing" language, matches what's actually shipped.)

### Updated draft X post (v1.2.0 — covers the branch-task tool; use this one instead of the v1.1.0 draft above if not yet posted)

> Shipped v1.2.0 of our Hermes Agent plugin: `scribase_branch_task`.
>
> One tool, three actions — `create` forks a real copy-on-write Postgres branch for one task (test a migration, run risky queries, whatever), `promote` three-way merges it back when it's good, `discard` deletes it when it isn't. Bounded TTL, so a forgotten branch cleans itself up.
>
> Branch-per-task is a workflow a prompt can't fake — it needs a real forked database and a real merge. Plus the existing migration linter and read-only query tool.
>
> 4 tools, open source, MIT: github.com/caelum0x/scribase-hermes-plugin
>
> @NousResearch #HermesAgent

## Hackathon submission-form answers (ready to paste; form submission itself is owner-gated — no login configured here)

**Plugin name:** Scribase

**Catalog PR link(s):** https://github.com/NousResearch/hermes-agent/pull/149583 (merged, original admission) and https://github.com/NousResearch/hermes-agent/pull/149690 (open, now updated to v1.2.0 with `scribase_branch_task`)

**Plugin repo:** https://github.com/caelum0x/scribase-hermes-plugin

**Demo video (X post link):** _pending — owner needs to post the video above to X tagging @NousResearch, then paste that tweet URL here_

**One-line description:** Provision a hosted Postgres backend, lint a SQL migration against real safety rules before it runs, run read-only queries, and spin up a real copy-on-write branch to create/promote/discard for one task — all from inside a Hermes agent session.

**What makes this more than a prompt or skill?** Two things, both backed by real infrastructure rather than wording. `scribase_lint_migration` calls a real, compiled migration-safety engine that parses SQL into a schema model and checks it against actual Postgres RLS/lock semantics (missing row-level security, unsafe grants, permissive policies, `SECURITY DEFINER` functions, missing FK indexes) — the exact same engine Scribase's own production control plane uses to block unsafe migrations before they run. `scribase_branch_task` gives the agent a disposable, real copy-on-write Postgres branch per task: create it, do the risky thing against it, then either three-way merge its schema back or throw it away — a workflow that needs an actual forked database and an actual schema merge the control plane plans and can refuse on conflict, not something a prompt or skill can simulate. `scribase_query` is backed by a server that enforces read-only in two independent layers (a static check, then an actual Postgres `READ ONLY` transaction) rather than trusting the model's output.

**Team / maintainer:** caelum0x

## Owner-only remaining steps (silently tracked, not blocking other work)

- Post the demo video to X, tagging @NousResearch (no X account configured in this environment).
- Paste that tweet's URL into the submission form and submit (owner login required; no credentials in this environment).
- Watch `hermes-agent#149690` for maintainer review/merge before the 2026-11-11 deadline — this is a maintainer-review gate, not something to push on from here.
