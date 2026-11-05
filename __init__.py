"""Scribase plugin for Hermes Agent — registration.

Registers exactly one tool, `scribase_create_project`, that provisions a
new hosted Postgres backend project on Scribase (https://api.scribase.com)
through its public REST API and returns the new environment's connection
string and API keys.

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

from agent.secret_scope import get_secret

from . import schemas, tools

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://api.scribase.com"


def register(ctx) -> None:
    """Wire the `scribase_create_project` tool to the Scribase REST client."""

    def _handle_create_project(args: dict, **kwargs) -> str:
        api_key = get_secret("SCRIBASE_API_KEY") or ""
        if not api_key:
            return json.dumps({
                "error": (
                    "SCRIBASE_API_KEY is not set. Create a Scribase organization "
                    "API key (console: Organization -> API tokens, or "
                    "POST /v1/organizations/{org}/api-keys) and configure it for "
                    "this plugin."
                ),
            })
        api_base = str(
            ctx.get_config("api_base_url", _DEFAULT_API_BASE) or _DEFAULT_API_BASE
        ).strip().rstrip("/")
        try:
            result = tools.create_project(args, api_key=api_key, api_base=api_base)
        except Exception as exc:  # a tool handler must never raise (dev guide, "Common mistakes")
            logger.exception("scribase_create_project failed")
            result = {"error": f"unexpected error: {exc}"}
        return json.dumps(result)

    ctx.register_tool(
        name="scribase_create_project",
        toolset="scribase",
        schema=schemas.SCRIBASE_CREATE_PROJECT,
        handler=_handle_create_project,
    )
