"""HTTP client for Scribase's public /v1 management API.

Every function here takes an already-resolved `api_key`/`api_base` and
returns a plain dict — never raises. The caller (`__init__.py`'s tool
handler) is responsible for the handler contract (always return a JSON
string, success or error alike). This module makes network calls only to
`api_base` (default `https://api.scribase.com`, overridable via the
plugin's optional `api_base_url` config key for self-hosted Scribase
clusters) and uses only the Python standard library — no third-party
dependencies.

Three tools, three endpoints:

- `create_project` — `PUT .../projects/{id}` + `POST /v1/environments`,
  provisions real billable resources.
- `lint_migration` — `POST .../migrations` with `"apply": false` always
  hardcoded here, so it only ever runs the control plane's migration
  linter (missing-RLS, unsafe-grant, lock-unsafe-DDL style rules) and never
  touches the tenant database.
- `run_query` — `POST .../database/query`, a statement the control plane
  itself runs inside a Postgres `READ ONLY` transaction; this client does
  not add its own write guard because the server enforces it twice
  (lexically, then transactionally).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Optional, Tuple

_TIMEOUT = 20  # seconds per HTTP call
_POLL_ATTEMPTS = 8
_POLL_INTERVAL = 3  # seconds
_DEFAULT_REGION = "eu-frankfurt"
_DEFAULT_POSTGRES_MAJOR = 17
_DEFAULT_ENVIRONMENT_ID = "production"
_TERMINAL_STATES = ("succeeded", "failed", "cancelled")


def _request(
    method: str, url: str, api_key: str,
    body: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Any]:
    """One HTTP call against the Scribase management API.

    Returns ``(status, parsed_body)``. ``status`` is 0 when the request
    could not be sent at all (DNS/connection failure); callers treat that
    as a terminal error, never a retryable one, to avoid hanging an
    unattended run (plugin-catalog rule 12).
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except urllib.error.URLError as exc:
        return 0, {"error": f"could not reach the Scribase API: {exc.reason}"}
    if not raw:
        return status, {}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"error": raw[:500]}


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def create_project(args: Dict[str, Any], *, api_key: str, api_base: str) -> Dict[str, Any]:
    """Create a Scribase project and its first environment, then return connection info.

    Required args: ``organization_id``, ``project_id``. Optional:
    ``environment_id`` (default "production"), ``region`` (default
    "eu-frankfurt", hosted Scribase's region), ``postgres_major`` (default
    17, the only currently supported version).
    """
    org = str(args.get("organization_id") or "").strip()
    project = str(args.get("project_id") or "").strip()
    environment = str(args.get("environment_id") or "").strip() or _DEFAULT_ENVIRONMENT_ID
    region = str(args.get("region") or "").strip() or _DEFAULT_REGION
    try:
        postgres_major = int(args.get("postgres_major") or _DEFAULT_POSTGRES_MAJOR)
    except (TypeError, ValueError):
        return {"error": "postgres_major must be an integer (only 17 is currently supported)."}

    if not org:
        return {"error": "organization_id is required (the existing Scribase org this project belongs to)."}
    if not project:
        return {"error": "project_id is required."}

    # 1. Create (or confirm) the project — idempotent PUT.
    status, body = _request(
        "PUT", f"{api_base}/v1/organizations/{org}/projects/{project}", api_key,
        body={"region": region, "postgres_major": postgres_major},
        extra_headers={"Idempotency-Key": _idempotency_key()},
    )
    if status == 0:
        return body
    if status not in (200, 201):
        return {"error": "failed to create project", "status": status, "detail": body}

    # 2. Create its first environment — async; returns an operation to poll.
    status, body = _request(
        "POST", f"{api_base}/v1/environments", api_key,
        body={
            "organization_id": org, "project_id": project, "environment_id": environment,
            "kind": "production", "data_mode": "schema_only",
            "region": region, "postgres_major": postgres_major, "ttl_hours": None,
        },
        extra_headers={"Idempotency-Key": _idempotency_key()},
    )
    if status == 0:
        return body
    if status != 202:
        return {"error": "failed to create environment", "status": status, "detail": body}
    operation_id = body.get("id")

    # 3. Poll the operation until it leaves pending/running/waiting_retry, bounded so an
    #    unattended run (cron, gateway) can never hang on this tool call (rule 12).
    final_state = None
    last_op_body: Dict[str, Any] = {}
    for _ in range(_POLL_ATTEMPTS):
        time.sleep(_POLL_INTERVAL)
        op_status, op_body = _request(
            "GET", f"{api_base}/v1/operations/{operation_id}", api_key,
            extra_headers={"X-Scribase-Organization-ID": org},
        )
        if op_status == 200:
            last_op_body = op_body
            final_state = op_body.get("state")
            if final_state in _TERMINAL_STATES:
                break

    if final_state != "succeeded":
        still_going = final_state not in ("failed", "cancelled")
        return {
            "status": "provisioning" if still_going else "failed",
            "organization_id": org, "project_id": project, "environment_id": environment,
            "operation_id": operation_id,
            "message": (
                f"Environment is still provisioning (state={final_state!r}). Call this tool "
                f"again shortly, or poll GET /v1/operations/{operation_id} directly."
                if still_going else
                f"Environment provisioning failed (state={final_state!r})."
            ),
            "operation": last_op_body,
        }

    # 4. Fetch the new environment's API keys and connection string.
    status, keys = _request(
        "GET",
        f"{api_base}/v1/organizations/{org}/projects/{project}/environments/{environment}/api-keys",
        api_key,
    )
    if status != 200:
        return {
            "status": "ready",
            "warning": "environment created, but failed to read its API keys",
            "detail": keys,
        }

    status, conn = _request(
        "GET",
        f"{api_base}/v1/organizations/{org}/projects/{project}/environments/{environment}/connection",
        api_key,
    )
    connection_uri = conn.get("connection_uri") if status == 200 else None

    return {
        "status": "ready",
        "organization_id": org,
        "project_id": project,
        "environment_id": environment,
        "region": region,
        "api_url": keys.get("api_url"),
        "anon_key": keys.get("anon_key"),
        "publishable_key": keys.get("publishable_key"),
        "service_role_key": keys.get("service_role_key"),
        "secret_key": keys.get("secret_key"),
        "connection_uri": connection_uri,
    }


def lint_migration(args: Dict[str, Any], *, api_key: str, api_base: str) -> Dict[str, Any]:
    """Lint one migration's SQL against Scribase's real migration-safety rules.

    Calls ``POST .../migrations`` with a single ``migration`` entry and
    ``"apply": false`` (hardcoded here, never read from ``args``) — this is
    the control plane's own dry-run path: the migration is parsed into a
    schema model and run through the blocking rules (missing RLS, GRANT to
    PUBLIC, a permissive `USING (true)` policy, a write policy with no `WITH
    CHECK`, a `SECURITY DEFINER` function) and the one advisory rule (a
    foreign key with no supporting index), but nothing ever touches the
    tenant database — the control plane only opens a database session when
    ``apply`` is true and the lint is clean, which this call can never
    request.
    """
    org = str(args.get("organization_id") or "").strip()
    project = str(args.get("project_id") or "").strip()
    environment = str(args.get("environment_id") or "").strip()
    up = str(args.get("up") or "").strip()
    down = args.get("down")
    name = str(args.get("migration_name") or "").strip() or "hermes_lint_check"

    if not org:
        return {"error": "organization_id is required."}
    if not project:
        return {"error": "project_id is required."}
    if not environment:
        return {"error": "environment_id is required."}
    if not up:
        return {"error": "up is required (the migration's forward SQL to lint)."}

    migration: Dict[str, Any] = {
        "version": time.strftime("%Y%m%d%H%M%S", time.gmtime()),
        "name": name,
        "up": up,
    }
    if down:
        migration["down"] = str(down)

    status, body = _request(
        "POST",
        f"{api_base}/v1/organizations/{org}/projects/{project}/environments/{environment}/migrations",
        api_key,
        # "apply" is always False here — this tool only ever lints.
        body={"migration": migration, "apply": False},
    )
    if status == 0:
        return body
    if status != 200:
        return {"error": "migration lint request failed", "status": status, "detail": body}

    findings = body.get("lintFindings", []) if isinstance(body, dict) else []
    blocking = [f for f in findings if isinstance(f, dict) and f.get("severity") == "BLOCK"]
    warnings = [f for f in findings if isinstance(f, dict) and f.get("severity") == "WARN"]

    return {
        "status": "blocked" if blocking else ("warnings" if warnings else "clean"),
        "safe_to_apply": not blocking,
        "blocking_findings": blocking,
        "warning_findings": warnings,
        "plan": body.get("plan") if isinstance(body, dict) else None,
    }


def run_query(args: Dict[str, Any], *, api_key: str, api_base: str) -> Dict[str, Any]:
    """Run one read-only statement via ``POST .../database/query``.

    The control plane itself enforces read-only in two independent layers
    (a static keyword check, then a Postgres `READ ONLY` transaction with a
    bounded statement timeout), so this client adds no SQL-shape validation
    of its own — any write/DDL statement is rejected by the server, not
    silently reinterpreted here.
    """
    org = str(args.get("organization_id") or "").strip()
    project = str(args.get("project_id") or "").strip()
    environment = str(args.get("environment_id") or "").strip()
    query = str(args.get("query") or "").strip()

    if not org:
        return {"error": "organization_id is required."}
    if not project:
        return {"error": "project_id is required."}
    if not environment:
        return {"error": "environment_id is required."}
    if not query:
        return {"error": "query is required (a single read-only SQL statement)."}

    body: Dict[str, Any] = {"query": query}
    limit = args.get("limit")
    if limit is not None:
        try:
            body["limit"] = int(limit)
        except (TypeError, ValueError):
            return {"error": "limit must be an integer between 1 and 1000."}

    status, result = _request(
        "POST",
        f"{api_base}/v1/organizations/{org}/projects/{project}/environments/{environment}/database/query",
        api_key,
        body=body,
    )
    if status == 0:
        return result
    if status != 200:
        return {"error": "query failed", "status": status, "detail": result}
    return result
