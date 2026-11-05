"""Scribase plugin for Hermes Agent — registration.

Registers four tools against Scribase's public REST API
(https://api.scribase.com):

- `scribase_create_project` — provisions a new hosted Postgres backend
  project and returns its connection string and API keys.
- `scribase_lint_migration` — submits a migration's SQL to Scribase's real
  migration-safety linter (missing-RLS, unsafe grants/policies, etc.) and
  returns Block/Warn findings. `apply` is always sent as `false`; this tool
  can never run the migration, only check it.
- `scribase_query` — runs a single read-only SQL statement against a
  project's database and returns the rows. The control plane enforces
  read-only itself (a static check, then a Postgres `READ ONLY`
  transaction), so this can never write or alter data.
- `scribase_branch_task` — gives an agent a real, throwaway, copy-on-write
  Postgres branch for one task: `create` forks one from an existing
  environment with a bounded TTL, `promote` three-way merges its schema
  back into the parent (the control plane itself refuses a conflicting
  merge unless `force`, which it also refuses for an MFA-protected
  organization), `discard` deletes it outright. The parent is never touched
  except through that one explicit, server-validated merge.

Hermes surfaces used: `ctx.register_tool` only. No hooks, no middleware, no
CLI/slash commands, no runtime overrides of Hermes internals.

Network calls: only to `api_base_url` (default `https://api.scribase.com`,
overridable for a self-hosted Scribase cluster via the plugin's
`api_base_url` config key, never a secret) — see tools.py.

Credentials: the Scribase organization API key is read through Hermes's
secret scope (`agent.secret_scope.get_secret("SCRIBASE_API_KEY")`), per the
plugin-catalog's credential rule. This plugin never reads `.env` files or
`os.environ` directly, and stores no credentials of its own.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict

from agent.secret_scope import get_secret

from . import schemas, tools

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://api.scribase.com"

_MISSING_KEY_ERROR = {
    "error": (
        "SCRIBASE_API_KEY is not set. Create a Scribase organization "
        "API key (console: Organization -> API tokens, or "
        "POST /v1/organizations/{org}/api-keys) and configure it for "
        "this plugin."
    ),
}


def _api_base(ctx) -> str:
    return str(
        ctx.get_config("api_base_url", _DEFAULT_API_BASE) or _DEFAULT_API_BASE
    ).strip().rstrip("/")


def _make_handler(
    ctx,
    tool_name: str,
    call: Callable[..., Dict[str, Any]],
) -> Callable[..., str]:
    """Builds a tool handler that resolves the API key/base once per call,
    delegates to `call`, and always returns a JSON string — a handler must
    never raise (dev guide, "Common mistakes")."""

    def _handle(args: dict, **kwargs) -> str:
        api_key = get_secret("SCRIBASE_API_KEY") or ""
        if not api_key:
            return json.dumps(_MISSING_KEY_ERROR)
        try:
            result = call(args, api_key=api_key, api_base=_api_base(ctx))
        except Exception as exc:  # noqa: BLE001 - handler contract: never raise
            logger.exception("%s failed", tool_name)
            result = {"error": f"unexpected error: {exc}"}
        return json.dumps(result)

    return _handle


def register(ctx) -> None:
    """Wires all four Scribase tools to the Scribase REST client."""

    ctx.register_tool(
        name="scribase_create_project",
        toolset="scribase",
        schema=schemas.SCRIBASE_CREATE_PROJECT,
        handler=_make_handler(ctx, "scribase_create_project", tools.create_project),
    )

    ctx.register_tool(
        name="scribase_lint_migration",
        toolset="scribase",
        schema=schemas.SCRIBASE_LINT_MIGRATION,
        handler=_make_handler(ctx, "scribase_lint_migration", tools.lint_migration),
    )

    ctx.register_tool(
        name="scribase_query",
        toolset="scribase",
        schema=schemas.SCRIBASE_QUERY,
        handler=_make_handler(ctx, "scribase_query", tools.run_query),
    )

    ctx.register_tool(
        name="scribase_branch_task",
        toolset="scribase",
        schema=schemas.SCRIBASE_BRANCH_TASK,
        handler=_make_handler(ctx, "scribase_branch_task", tools.branch_task),
    )
