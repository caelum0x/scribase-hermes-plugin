"""Tool schema for `scribase_create_project` — this is what the LLM reads to
decide when and how to call the tool."""

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
