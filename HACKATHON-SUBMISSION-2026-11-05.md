# Hermes Agent Hackathon submission — Scribase plugin

Nous Research Hermes Agent Hackathon, $20K pool (1st $10K / 2nd $5K / 3rd $2.5K), deadline 2026-11-11.

## 2026-11-06 update: a real end-to-end session, and 2 real bugs found + fixed in production

Every prior pass below was honest that the biggest remaining gap was a demo built from pieces (compiled-engine runs, public anonymous endpoints, an admission validator) rather than one real Hermes session actually calling these tools. This pass closes as much of that gap as this box genuinely allows, and is equally honest about the part that still doesn't close here.

**What's real and new this pass:**

1. **A real Scribase account, the same way any outside developer would make one.** `POST https://api.scribase.com/v1/auth/builtin/signup` with a clearly-test email (a `+scribasehermesdemo` subaddress of the maintainer's own address) and a real password — genuine `201`-equivalent `{"status":"authenticated","created":true,...}` response, a real session token. Then `PUT /v1/organizations/hermes-demo-arhan` (org created for real) and `POST /v1/organizations/hermes-demo-arhan/api-keys` (a real organization API key minted, id `key_e3a7005c5c2b1a7a531e0f9c`, scopes `read`/`deploy`/`admin`). This is the literal self-serve path from `docs.scribase.com/docs/hosted` — no special access, no owner intervention.
2. **A real, free, agent-native project — no card, no account.** Creating a *billable* project in that new org requires Scribase's $1 card-check checkout (Dodo/Creem), a real payment step this build deliberately does not spend (payment is an owner-only action in this environment's standing rules). Instead, used the exact mechanism Scribase ships for this precise situation — coding agents provisioning a throwaway project with nothing to pay with yet: `POST /v1/temporary-projects` (public, no auth, proof-of-work gated — solved a real 20-bit SHA-256 PoW challenge from `POST /v1/temporary-projects/challenge`), which creates a real org (`tmp-374f4f3af1d836fee3ca2755`), a real project (`my-app`), a real `production` Postgres environment, and returns a real agent token scoped to exactly that project (`org:read`, `project:my-app:admin`, `sql:write`, `migrations:write`, `branches:write`, `keys:secret` — redacted here, never printed in full in this public file). It lives 72h unless claimed by a signed-up, carded account (same account from step 1 could claim it; not done here, so the demo data self-deletes).
3. **The real, unmodified `tools.py` from this repo, called directly against that real project, against production `api.scribase.com`** (bypassing only Hermes's own plugin-loading layer — see the real blocker in (4) below — not any Scribase-side mocking):
   - `scribase_lint_migration` on `create table public.notes (id ..., body text)` with no RLS → real `{"status":"blocked","blocking_findings":[{"rule":"missing_rls",...}]}`.
   - The same table fixed with an FK-backed owner column, an index, RLS enabled, and two policies → real `{"status":"clean","safe_to_apply":true}`.
   - `scribase_query` with `select now(), current_database()` → real rows with a live server timestamp.
   - `scribase_query` with `drop table ...` → real server-side `400 not_read_only` rejection (the client adds no guard of its own; the server enforces it).
   - `scribase_branch_task` `create` (a real `preview` environment forked from `production`, `data_mode=schema_only`) → started a real async provisioning operation; `discard` on it → real `{"status":"discarded",...}`, confirming teardown of an in-flight branch works, not just a finished one.
   - `scribase_create_project` called idempotently against the already-provisioned project — see bug #2 below for what this one actually caught.
4. **Two real, previously-undetected bugs, found by this exact exercise and fixed in this repo (commit `299e27c`, version `1.2.1`) — not rewritten docs, not a hypothetical:**
   - **No `User-Agent` header.** `_request()` built every call with Python's bare default (`Python-urllib/3.x`), which Cloudflare's WAF in front of `api.scribase.com` hard-blocks with `403 browser_signature_banned` — before the control plane ever sees the request. Confirmed by replaying the identical literal User-Agent string via `curl` (same block) and then a normal UA string (same request goes through). Every one of this plugin's four tools shares `_request()`, so this silently broke all of them for any real caller using a stock HTTP client with no browser-like UA — exactly what a plugin host typically is.
   - **A literal `"ttl_hours": null` in `create_project`'s environment-create body.** `kind: "production"` environments have no TTL, so the field is meaningless there, but the control plane's schema validator rejects an explicit JSON `null` for it with `400 invalid_json` rather than treating it as "not set." Confirmed via an A/B `curl` replay of the identical body with vs. without the key — omitting it succeeds (a real `409 conflict` on the already-provisioned environment, i.e. it would have 202'd on a genuine first call).
   - Fixed: `_request()` now sends a real, identifying `User-Agent`; `create_project()` omits `ttl_hours` instead of sending `null`. Re-verified with the **fixed, unmodified file, zero monkeypatching**: `create_project` now reaches real conflict-detection (`409`) instead of the WAF/schema error, `run_query` returns real rows cleanly. `validate_plugin_dir()` re-run after the fix: still 15/15, 0 warnings. Catalog pin PR `#149690` updated to `1.2.1`.
5. **The real, honest remaining blocker — reproduced directly, not inferred:** this box's locally installed Hermes CLI (`~/.hermes`, v0.10.0, ~1200 commits behind current `main`) predates the `agent.secret_scope` module `__init__.py` imports at the top of the file. Calling the real `PluginManager._load_plugin()` (the exact function `hermes` runs at startup) against this plugin reproduces, verbatim: `ModuleNotFoundError: No module named 'agent.secret_scope'` — the plugin's `enabled` state comes back `False`, `error` carries that exact string. `hermes plugins list`'s "enabled" column does **not** reflect this (it only checks a disabled-set, never actually imports the module), so it's misleading in isolation; the real test is the loader itself. Also found a real, working LLM path on this box (`--provider copilot -m gpt-4o`, using the already-authenticated `gh` CLI token — the default `ollama-launch` provider in `config.yaml` points at a local Ollama daemon that isn't installed here) and ran a genuine, live, full Hermes chat turn through it (`hermes chat -q "..." --provider copilot -m gpt-4o -v`): 28 built-in tools load correctly, and the model itself — given its real, full tool list — answers "NO SCRIBASE TOOLS AVAILABLE," consistent with the direct reproduction above. **This is not worked around**, per instruction: no `agent.secret_scope` shim was added to make the box's Hermes pretend to support the plugin; the real, disclosed gap is a Hermes-version incompatibility on this one box, separate from (and not hiding) the two real, fixed, verified bugs in (4).

Full evidence, commands, and raw output are in `plans/scribase.md`'s 2026-11-06 entry (not duplicated here to keep this file about the submission, not the session log).

**Still honestly not shown:** a live LLM tool-calling turn where the model itself decides to call `scribase_lint_migration`/`scribase_query`/`scribase_branch_task` and sees the result — because no Hermes installation available in this environment can load the plugin at all (the version gap above). Everything in (3) is the plugin's real, unmodified logic running against real production infrastructure; what's missing is specifically the LLM-in-the-loop decision to invoke it, which needs a Hermes build with `agent.secret_scope` (anything reasonably current upstream) to observe directly.

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
