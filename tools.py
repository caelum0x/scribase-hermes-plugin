"""HTTP client for Scribase's public /v1 management API.

Every function here takes an already-resolved `api_key`/`api_base` and
returns a plain dict — never raises. The caller (`__init__.py`'s tool
handler) is responsible for the handler contract (always return a JSON
string, success or error alike). This module makes network calls only to
`api_base` (default `https://api.scribase.com`, overridable via the
plugin's optional `api_base_url` config key for self-hosted Scribase
clusters) and uses only the Python standard library — no third-party
dependencies.

Four tools, four endpoints:

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
- `branch_task` — `POST /v1/environments` (`kind: "preview"`), `POST
  .../branches/merge`, and `DELETE .../environments/{env}`: a real
  copy-on-write Postgres branch an agent can create for one task, then
  either promote (merge its schema back) or discard (delete it), never
  touching the parent environment except through an explicit, auditable
  merge.
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

# A branch with a TTL of this many hours or less lands in Scribase's own
# "agent branch" slot pool instead of competing with human preview
# environments for the project's regular preview quota (confirmed against
# `control-api/src/adapters/usage.rs::AGENT_BRANCH_MAX_TTL_HOURS = 24` and
# `is_agent_branch()`). `scribase_branch_task` always sends a TTL in this
# range so an agent's branches never starve a human's preview slots, and so
# a branch nobody discards still self-deletes instead of running forever.
_AGENT_BRANCH_MAX_TTL_HOURS = 24
_DEFAULT_BRANCH_TTL_HOURS = 4
_VALID_DATA_MODES = ("snapshot", "sanitized", "schema_only")


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


def _poll_operation(
    operation_id: str, organization_id: str, *, api_key: str, api_base: str
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Polls `GET /v1/operations/{id}` until it leaves pending/running, bounded
    so an unattended run (cron, gateway) can never hang on one tool call
    (plugin-catalog rule 12). Returns ``(final_state, last_operation_body)``;
    ``final_state`` is ``None`` if every poll attempt was spent without the
    operation reaching a terminal state.
    """
    final_state: Optional[str] = None
    last_body: Dict[str, Any] = {}
    for _ in range(_POLL_ATTEMPTS):
        time.sleep(_POLL_INTERVAL)
        status, body = _request(
            "GET", f"{api_base}/v1/operations/{operation_id}", api_key,
            extra_headers={"X-Scribase-Organization-ID": organization_id},
        )
        if status == 200:
            last_body = body
            final_state = body.get("state")
            if final_state in _TERMINAL_STATES:
                break
    return final_state, last_body


def _read_environment_access(
    organization_id: str, project_id: str, environment_id: str, *, api_key: str, api_base: str
) -> Dict[str, Any]:
    """Reads back a ready environment's API keys and Postgres connection URI.

    Returns a dict always containing ``status`` (``"ready"`` or a
    ``"warning"``-carrying partial result) plus whichever of
    ``api_url``/``anon_key``/``publishable_key``/``service_role_key``/
    ``secret_key``/``connection_uri`` could be read.
    """
    status, keys = _request(
        "GET",
        f"{api_base}/v1/organizations/{organization_id}/projects/{project_id}"
        f"/environments/{environment_id}/api-keys",
        api_key,
    )
    if status != 200:
        return {
            "status": "ready",
            "warning": "environment is ready, but failed to read its API keys",
            "detail": keys,
        }

    status, conn = _request(
        "GET",
        f"{api_base}/v1/organizations/{organization_id}/projects/{project_id}"
        f"/environments/{environment_id}/connection",
        api_key,
    )
    connection_uri = conn.get("connection_uri") if status == 200 else None

    return {
        "status": "ready",
        "api_url": keys.get("api_url"),
        "anon_key": keys.get("anon_key"),
        "publishable_key": keys.get("publishable_key"),
        "service_role_key": keys.get("service_role_key"),
        "secret_key": keys.get("secret_key"),
        "connection_uri": connection_uri,
    }


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
    final_state, last_op_body = _poll_operation(operation_id, org, api_key=api_key, api_base=api_base)

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
    access = _read_environment_access(org, project, environment, api_key=api_key, api_base=api_base)
    if access.get("status") != "ready" or "warning" in access:
        return access
    return {
        "organization_id": org,
        "project_id": project,
        "environment_id": environment,
        "region": region,
        **access,
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


def branch_task(args: Dict[str, Any], *, api_key: str, api_base: str) -> Dict[str, Any]:
    """Dispatches one of three real, agent-native lifecycle actions on a
    throwaway, real copy-on-write Postgres branch:

    - ``"create"`` — cuts a new branch environment from a parent (default
      ``"production"``), with a bounded TTL that keeps it in Scribase's
      dedicated agent-branch slot pool, then returns its connection string
      and API keys, same shape as `create_project`.
    - ``"promote"`` — three-way merges the branch's schema back into its
      parent via ``POST .../branches/merge``. The server applies the merge
      only when it is conflict-free, or when ``force`` is set and the
      organization has no MFA factor (an MFA-protected organization's API
      key cannot answer the step-up challenge a forced merge requires —
      the server rejects it with ``mfa_required`` rather than silently
      skipping the check, and this client returns that rejection verbatim).
    - ``"discard"`` — deletes the branch outright via ``DELETE
      .../environments/{env}``, instead of waiting for its TTL.

    No action ever touches the parent environment except an applied
    promote, and even that is a schema-only three-way merge the control
    plane itself plans and can refuse on conflict.
    """
    action = str(args.get("action") or "").strip().lower()
    org = str(args.get("organization_id") or "").strip()
    project = str(args.get("project_id") or "").strip()

    if not org:
        return {"error": "organization_id is required."}
    if not project:
        return {"error": "project_id is required."}

    if action == "create":
        return _branch_create(args, org, project, api_key=api_key, api_base=api_base)
    if action == "promote":
        return _branch_promote(args, org, project, api_key=api_key, api_base=api_base)
    if action == "discard":
        return _branch_discard(args, org, project, api_key=api_key, api_base=api_base)
    return {"error": "action must be one of: create, promote, discard."}


def _branch_create(
    args: Dict[str, Any], org: str, project: str, *, api_key: str, api_base: str
) -> Dict[str, Any]:
    """``create``: cuts a new ``kind: "preview"`` environment forked from
    ``base_environment_id`` (default ``"production"``). The control plane
    captures the parent's schema as the branch's merge base automatically on
    creation — no separate `POST .../branches` call is needed (confirmed by
    reading `control-api/src/http/previews.rs::provision_environment()`,
    which calls `branch::record_fork_point` itself whenever a preview is cut
    from an explicit or implicit base). If that capture fails, the server
    reports it as a top-level `branch_lineage_error` on this same response;
    this client surfaces it as `branch_lineage_warning` rather than dropping
    it, since a branch with no recorded merge base cannot later be promoted.
    """
    base = str(args.get("base_environment_id") or "").strip() or _DEFAULT_ENVIRONMENT_ID
    branch_id = str(args.get("environment_id") or "").strip() or f"agent-{uuid.uuid4().hex[:8]}"
    data_mode = str(args.get("data_mode") or "").strip() or "snapshot"
    region = str(args.get("region") or "").strip() or _DEFAULT_REGION
    try:
        postgres_major = int(args.get("postgres_major") or _DEFAULT_POSTGRES_MAJOR)
    except (TypeError, ValueError):
        return {"error": "postgres_major must be an integer (only 17 is currently supported)."}
    try:
        ttl_hours = int(args.get("ttl_hours") or _DEFAULT_BRANCH_TTL_HOURS)
    except (TypeError, ValueError):
        return {"error": "ttl_hours must be an integer."}

    if branch_id == base:
        return {"error": "a branch cannot be its own base environment."}
    if data_mode not in _VALID_DATA_MODES:
        return {"error": f"data_mode must be one of: {', '.join(_VALID_DATA_MODES)}."}
    if not 1 <= ttl_hours <= _AGENT_BRANCH_MAX_TTL_HOURS:
        return {
            "error": (
                f"ttl_hours must be between 1 and {_AGENT_BRANCH_MAX_TTL_HOURS} — a branch "
                "this tool creates always stays in Scribase's agent-branch slot pool, never "
                "the human preview pool, and this is its allowed TTL range."
            )
        }

    status, body = _request(
        "POST", f"{api_base}/v1/environments", api_key,
        body={
            "organization_id": org, "project_id": project, "environment_id": branch_id,
            "kind": "preview", "data_mode": data_mode, "region": region,
            "postgres_major": postgres_major, "ttl_hours": ttl_hours,
            "base_environment_id": base,
        },
        extra_headers={"Idempotency-Key": _idempotency_key()},
    )
    if status == 0:
        return body
    if status not in (200, 202):
        return {"error": "failed to create branch", "status": status, "detail": body}
    lineage_warning = body.get("branch_lineage_error") if isinstance(body, dict) else None
    operation_id = body.get("id") if isinstance(body, dict) else None
    if not operation_id:
        return {"error": "branch create accepted but no operation id was returned", "detail": body}

    final_state, last_op_body = _poll_operation(operation_id, org, api_key=api_key, api_base=api_base)
    if final_state != "succeeded":
        still_going = final_state not in ("failed", "cancelled")
        result = {
            "status": "provisioning" if still_going else "failed",
            "organization_id": org, "project_id": project,
            "environment_id": branch_id, "base_environment_id": base,
            "operation_id": operation_id,
            "message": (
                f"Branch is still provisioning (state={final_state!r}). Call this tool again "
                f"shortly with action='create' and the same environment_id, or poll "
                f"GET /v1/operations/{operation_id} directly."
                if still_going else
                f"Branch provisioning failed (state={final_state!r})."
            ),
            "operation": last_op_body,
        }
        if lineage_warning:
            result["branch_lineage_warning"] = lineage_warning
        return result

    access = _read_environment_access(org, project, branch_id, api_key=api_key, api_base=api_base)
    result = {
        "organization_id": org,
        "project_id": project,
        "environment_id": branch_id,
        "base_environment_id": base,
        "data_mode": data_mode,
        "ttl_hours": ttl_hours,
        "region": region,
        **access,
        "next_step": (
            "When the task is done, call this tool again with action='promote' to merge "
            "this branch's schema back into "
            f"{base!r}, or action='discard' to delete it immediately. Otherwise it "
            f"self-deletes in {ttl_hours}h."
        ),
    }
    if lineage_warning:
        result["branch_lineage_warning"] = lineage_warning
    return result


def _branch_promote(
    args: Dict[str, Any], org: str, project: str, *, api_key: str, api_base: str
) -> Dict[str, Any]:
    """``promote``: three-way merges ``environment_id`` (the branch, "head")
    into ``base_environment_id`` (default ``"production"``) via ``POST
    .../branches/merge``. Reads the real response fields the control plane
    renders (`merge_to_json` in `control-api/src/adapters/branch.rs`) —
    ``applied``/``clean``/``changes``/``conflicts``/``statements`` — rather
    than the simplified ``merged`` field the docs page's example shows,
    since the compiled server is what actually answers.
    """
    head = str(args.get("environment_id") or "").strip()
    base = str(args.get("base_environment_id") or "").strip() or _DEFAULT_ENVIRONMENT_ID
    force = bool(args.get("force"))
    dry_run = bool(args.get("dry_run"))

    if not head:
        return {"error": "environment_id is required (the branch to promote)."}
    if head == base:
        return {"error": "a branch cannot be promoted into itself."}

    status, body = _request(
        "POST",
        f"{api_base}/v1/organizations/{org}/projects/{project}/branches/merge",
        api_key,
        body={"base": base, "head": head, "force": force, "dry_run": dry_run},
    )
    if status == 0:
        return body
    if status != 200 or not isinstance(body, dict):
        # Real, common failures here: 409 branch_not_registered / merge_base_mismatch,
        # 403 mfa_required (a forced merge on an MFA-protected organization), 422
        # merge_rejected, 429 rate_limited. The server's detail explains which.
        return {"error": "promote (merge) failed", "status": status, "detail": body}

    applied = bool(body.get("applied"))
    clean = bool(body.get("clean"))
    conflicts = body.get("conflicts") or []
    changes = body.get("changes") or []
    if applied:
        branch_status = "merged"
    elif conflicts:
        branch_status = "blocked_by_conflicts"
    elif dry_run:
        branch_status = "dry_run_clean"
    else:
        branch_status = "no_changes"

    result = {
        "status": branch_status,
        "base_environment_id": base,
        "environment_id": head,
        "applied": applied,
        "dry_run": dry_run,
        "clean": clean,
        "changes": changes,
        "conflicts": conflicts,
        "statements": body.get("statements") or [],
        "fork_base_trusted": body.get("fork_base_trusted"),
        "fork_base_origin": body.get("fork_base_origin"),
    }
    if body.get("warnings"):
        result["warnings"] = body["warnings"]
    return result


def _branch_discard(
    args: Dict[str, Any], org: str, project: str, *, api_key: str, api_base: str
) -> Dict[str, Any]:
    """``discard``: deletes ``environment_id`` via ``DELETE
    .../environments/{env}`` instead of waiting for its TTL. Deletion is
    permanent and unconditional — there is no confirmation step, matching
    the real endpoint's own contract ("Deletion is permanent.", per
    `docs.scribase.com/docs/api/environments`).
    """
    branch_id = str(args.get("environment_id") or "").strip()
    if not branch_id:
        return {"error": "environment_id is required (the branch to discard)."}

    status, body = _request(
        "DELETE",
        f"{api_base}/v1/organizations/{org}/projects/{project}/environments/{branch_id}",
        api_key,
        extra_headers={"Idempotency-Key": _idempotency_key()},
    )
    if status == 0:
        return body
    if status != 202:
        return {"error": "failed to discard branch", "status": status, "detail": body}
    operation_id = body.get("id") if isinstance(body, dict) else None
    if not operation_id:
        return {"error": "branch discard accepted but no operation id was returned", "detail": body}

    final_state, last_op_body = _poll_operation(operation_id, org, api_key=api_key, api_base=api_base)
    if final_state == "succeeded":
        return {"status": "discarded", "organization_id": org, "project_id": project, "environment_id": branch_id}
    still_going = final_state not in ("failed", "cancelled")
    return {
        "status": "discarding" if still_going else "failed",
        "organization_id": org,
        "project_id": project,
        "environment_id": branch_id,
        "operation_id": operation_id,
        "message": (
            f"Branch is still being discarded (state={final_state!r}). It will finish shortly."
            if still_going else
            f"Branch discard failed (state={final_state!r})."
        ),
        "operation": last_op_body,
    }
