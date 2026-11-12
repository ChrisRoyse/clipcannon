"""The MCP refusal contract: every error is ``{code, message, remediation}``.

Doctrine #65 §4. Tool handlers return ``{"error": {...}}`` dicts or raise; this
module is the single boundary that turns both, plus argument-schema
violations, into the same typed shape before anything reaches the client.
"""

from __future__ import annotations

from typing import Any

from clipcannon.exceptions import (
    ConfigError,
    DatabaseError,
    PipelineError,
    ProvenanceError,
)

GENERIC_REMEDIATION = (
    "Read error.message and error.details, correct the request or the named "
    "precondition, and call the tool again. Nothing was changed by this call "
    "unless the message says otherwise."
)

REMEDIATION: dict[str, str] = {
    "INVALID_ARGUMENTS": (
        "Fix the argument named in details.path so it satisfies details.constraint "
        "(see the tool's inputSchema from list_tools) and call again."
    ),
    "UNKNOWN_TOOL": "Call list_tools and use one of the names in details.available_tools.",
    "PROJECT_NOT_FOUND": (
        "Call clipcannon_project_list for valid project ids, or create one with "
        "clipcannon_project_create and run clipcannon_ingest."
    ),
    "MISSING_PARAMETER": "Supply the parameter named in the message and call again.",
    "INVALID_PARAMETER": "Correct the parameter named in the message to an allowed value.",
    "FILE_NOT_FOUND": "Check the path exists on the server host (absolute path) and retry.",
    "NOT_FOUND": "List the parent collection to get a valid id, then retry with it.",
    "INVALID_STATE": "Bring the object to the required state named in the message first.",
    "CONFIG_INVALID": (
        "Fix ~/.clipcannon/config.json (valid JSON, keys from config/default_config.json) "
        "or remove it to use the shipped defaults; then retry."
    ),
    "DATABASE_ERROR": (
        "Check the project's analysis.db exists and is not locked or corrupt "
        "(clipcannon_project_status); re-ingest the project if the schema is damaged."
    ),
    "PIPELINE_ERROR": (
        "Inspect clipcannon_project_status for the failed stage, fix its "
        "prerequisite, and re-run ingest for that project."
    ),
    "PROVENANCE_ERROR": (
        "Verify the project's provenance chain; a broken chain means project state "
        "was modified outside ClipCannon and the project must be re-ingested."
    ),
    "INTERNAL_ERROR": (
        "This is an unclassified failure: read error.message and the MCP server's "
        "stderr log (it carries the traceback), fix the cause, and retry."
    ),
}

_EXC_CODES: tuple[tuple[type[BaseException], str], ...] = (
    (ConfigError, "CONFIG_INVALID"),
    (DatabaseError, "DATABASE_ERROR"),
    (PipelineError, "PIPELINE_ERROR"),
    (ProvenanceError, "PROVENANCE_ERROR"),
)


def remediation_for(code: str) -> str:
    return REMEDIATION.get(code, GENERIC_REMEDIATION)


def ensure_contract(result: object) -> object:
    """Give any ``{"error": {...}}`` result a code and a remediation."""
    if isinstance(result, dict) and isinstance(result.get("error"), dict):
        err = result["error"]
        err.setdefault("code", "INTERNAL_ERROR")
        details = err.get("details")
        if not err.get("remediation") and isinstance(details, dict) and details.get("remediation"):
            err["remediation"] = details["remediation"]  # handler-specific guidance wins
        if not err.get("remediation"):
            err["remediation"] = remediation_for(str(err["code"]))
    return result


def exception_error(exc: BaseException, tool: str) -> dict[str, Any]:
    """Typed error for an exception that escaped a tool handler."""
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or not code:
        code = next((c for t, c in _EXC_CODES if isinstance(exc, t)), "INTERNAL_ERROR")
    remediation = getattr(exc, "remediation", None) or remediation_for(code)
    details: dict[str, Any] = {"tool": tool, "exception": type(exc).__name__}
    extra = getattr(exc, "details", None)
    if isinstance(extra, dict):
        details.update(extra)
    return {"error": {"code": code, "message": str(exc) or type(exc).__name__,
                      "remediation": remediation, "details": details}}


def validate_arguments(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any] | None:
    """Validate ``args`` against a tool inputSchema; typed error or None."""
    from jsonschema import validators
    from jsonschema.exceptions import best_match

    cls = validators.validator_for(schema)
    error = best_match(cls(schema).iter_errors(args))
    if error is None:
        return None
    path = "/".join(str(p) for p in error.absolute_path) or "(root)"
    return {"error": {
        "code": "INVALID_ARGUMENTS",
        "message": f"Argument {path!r} rejected: {error.message}",
        "remediation": REMEDIATION["INVALID_ARGUMENTS"],
        "details": {"path": path, "constraint": error.validator,
                    "expected": error.validator_value},
    }}
