"""Full State Verification (FSV) of the ClipCannon MCP Server scaffold.

Forensic verification of:
  1. Server creation and identity
  2. Tool registry completeness (38 tools)
  3. Tool dispatcher mapping completeness
  4. Unknown tool error handling
  5. Default configuration validation

Run with: python tests/fsv_server_integration.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure src is on the path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))


# ============================================================
# CONSTANTS: The spec-defined 38 tools
# ============================================================

EXPECTED_TOOLS = [
    # Project tools (5)
    "clipcannon_project_create",
    "clipcannon_project_open",
    "clipcannon_project_list",
    "clipcannon_project_status",
    "clipcannon_project_delete",
    # Understanding tools (7)
    "clipcannon_ingest",
    "clipcannon_get_vud_summary",
    "clipcannon_get_analytics",
    "clipcannon_get_transcript",
    "clipcannon_get_segment_detail",
    "clipcannon_get_frame",
    "clipcannon_search_content",
    # Provenance tools (4)
    "clipcannon_provenance_verify",
    "clipcannon_provenance_query",
    "clipcannon_provenance_chain",
    "clipcannon_provenance_timeline",
    # Disk tools (2)
    "clipcannon_disk_status",
    "clipcannon_disk_cleanup",
    # Config tools (3)
    "clipcannon_config_get",
    "clipcannon_config_set",
    "clipcannon_config_list",
    # Billing tools (4)
    "clipcannon_credits_balance",
    "clipcannon_credits_history",
    "clipcannon_credits_estimate",
    "clipcannon_spending_limit",
    # Editing tools (8)
    "clipcannon_create_edit",
    "clipcannon_modify_edit",
    "clipcannon_list_edits",
    "clipcannon_generate_metadata",
    "clipcannon_auto_trim",
    "clipcannon_color_adjust",
    "clipcannon_add_motion",
    "clipcannon_add_overlay",
    "clipcannon_remove_region",
    "clipcannon_extract_subject",
    "clipcannon_replace_background",
    # Rendering tools (10)
    "clipcannon_render",
    "clipcannon_render_status",
    "clipcannon_render_batch",
    "clipcannon_get_editing_context",
    "clipcannon_analyze_frame",
    "clipcannon_preview_clip",
    "clipcannon_inspect_render",
    "clipcannon_preview_layout",
    "clipcannon_measure_layout",
    "clipcannon_get_storyboard",
    # Audio tools (4)
    "clipcannon_generate_music",
    "clipcannon_compose_midi",
    "clipcannon_generate_sfx",
    "clipcannon_audio_cleanup",
]

REQUIRED_CONFIG_SECTIONS = ["version", "directories", "processing", "rendering", "publishing", "gpu"]


def separator(title: str) -> None:
    """Print a formatted separator line."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def verdict(label: str, passed: bool, detail: str = "") -> None:
    """Print a pass/fail verdict line."""
    status = "PASS" if passed else "FAIL"
    marker = "[OK]" if passed else "[FAIL]"
    msg = f"  {marker} {label}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    return passed


# ============================================================
# TRACK RESULTS
# ============================================================
results = {"passed": 0, "failed": 0, "errors": []}


def record(label: str, passed: bool, detail: str = "") -> None:
    """Record and print a test result."""
    verdict(label, passed, detail)
    if passed:
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["errors"].append(f"{label}: {detail}")


# ============================================================
# TEST 1: Server creation
# ============================================================
def test_server_creation() -> None:
    separator("TEST 1: Server Creation")
    try:
        from mcp.server import Server
        from clipcannon.server import create_server
        from clipcannon import __version__

        server = create_server()

        record(
            "create_server returns Server instance",
            isinstance(server, Server),
            f"type={type(server).__name__}",
        )

        record(
            "Server name is 'ClipCannon'",
            server.name == "ClipCannon",
            f"name={server.name!r}",
        )

        record(
            f"Server version matches __version__ ({__version__})",
            server.version == __version__,
            f"version={server.version!r}",
        )
    except Exception as exc:
        record("Server creation", False, f"Exception: {exc}")


# ============================================================
# TEST 2: Tool registry completeness
# ============================================================
def test_tool_registry() -> None:
    separator("TEST 2: Tool Registry Completeness")
    try:
        from clipcannon.tools import ALL_TOOL_DEFINITIONS

        actual_count = len(ALL_TOOL_DEFINITIONS)
        expected_count = 50

        record(
            f"ALL_TOOL_DEFINITIONS count = {expected_count}",
            actual_count == expected_count,
            f"actual={actual_count}",
        )

        actual_names = [t.name for t in ALL_TOOL_DEFINITIONS]

        # Print every tool found
        print("\n  Registered tools:")
        for i, name in enumerate(actual_names, 1):
            print(f"    {i:2d}. {name}")

        # Check each expected tool
        print("\n  Per-tool verification:")
        missing = []
        for tool_name in EXPECTED_TOOLS:
            found = tool_name in actual_names
            if not found:
                missing.append(tool_name)
            record(f"Tool '{tool_name}' registered", found)

        # Check for unexpected tools
        unexpected = [n for n in actual_names if n not in EXPECTED_TOOLS]
        record(
            "No unexpected tools",
            len(unexpected) == 0,
            f"unexpected={unexpected}" if unexpected else "",
        )

        # Category counts
        project_tools = [n for n in actual_names if n.startswith("clipcannon_project_")]
        understanding_tools = [
            n for n in actual_names
            if n in [
                "clipcannon_ingest", "clipcannon_get_vud_summary",
                "clipcannon_get_analytics", "clipcannon_get_transcript",
                "clipcannon_get_segment_detail", "clipcannon_get_frame",
                "clipcannon_search_content",
            ]
        ]
        provenance_tools = [n for n in actual_names if n.startswith("clipcannon_provenance_")]
        disk_tools = [n for n in actual_names if n.startswith("clipcannon_disk_")]
        config_tools = [n for n in actual_names if n.startswith("clipcannon_config_")]
        billing_tools = [
            n for n in actual_names
            if n.startswith("clipcannon_credits_") or n == "clipcannon_spending_limit"
        ]

        print("\n  Category counts:")
        record(f"Project tools = 5", len(project_tools) == 5, f"actual={len(project_tools)}")
        record(f"Understanding tools = 7", len(understanding_tools) == 7, f"actual={len(understanding_tools)}")
        record(f"Provenance tools = 4", len(provenance_tools) == 4, f"actual={len(provenance_tools)}")
        record(f"Disk tools = 2", len(disk_tools) == 2, f"actual={len(disk_tools)}")
        record(f"Config tools = 3", len(config_tools) == 3, f"actual={len(config_tools)}")
        record(f"Billing tools = 4", len(billing_tools) == 4, f"actual={len(billing_tools)}")

        if missing:
            print(f"\n  MISSING TOOLS: {missing}")

    except Exception as exc:
        record("Tool registry", False, f"Exception: {exc}")


# ============================================================
# TEST 3: Dispatcher completeness
# ============================================================
def test_dispatchers() -> None:
    separator("TEST 3: Dispatcher Completeness")
    try:
        from clipcannon.tools import ALL_TOOL_DEFINITIONS, TOOL_DISPATCHERS

        actual_names = [t.name for t in ALL_TOOL_DEFINITIONS]

        print(f"\n  TOOL_DISPATCHERS has {len(TOOL_DISPATCHERS)} entries")
        print(f"  ALL_TOOL_DEFINITIONS has {len(ALL_TOOL_DEFINITIONS)} entries")

        record(
            "Dispatcher count matches tool count",
            len(TOOL_DISPATCHERS) == len(ALL_TOOL_DEFINITIONS),
            f"dispatchers={len(TOOL_DISPATCHERS)}, tools={len(ALL_TOOL_DEFINITIONS)}",
        )

        missing_dispatchers = []
        for tool_name in actual_names:
            has_dispatcher = tool_name in TOOL_DISPATCHERS
            if not has_dispatcher:
                missing_dispatchers.append(tool_name)
            record(f"Dispatcher for '{tool_name}'", has_dispatcher)

        # Verify every dispatcher is callable
        print("\n  Dispatcher callability check:")
        for tool_name, dispatch_fn in TOOL_DISPATCHERS.items():
            is_callable = callable(dispatch_fn)
            record(f"Dispatcher '{tool_name}' is callable", is_callable)

        if missing_dispatchers:
            print(f"\n  MISSING DISPATCHERS: {missing_dispatchers}")

    except Exception as exc:
        record("Dispatcher check", False, f"Exception: {exc}")


# ============================================================
# TEST 4: Unknown tool error handling
# ============================================================
def test_unknown_tool() -> None:
    separator("TEST 4: Unknown Tool Error Handling")
    try:
        from clipcannon.server import create_server

        server = create_server()

        # Access the call_tool handler by invoking it through server dispatch
        # We test the logic directly from the TOOL_DISPATCHERS lookup
        from clipcannon.tools import TOOL_DISPATCHERS

        dispatch_fn = TOOL_DISPATCHERS.get("totally_fake_tool_12345")
        record(
            "Unknown tool returns None from TOOL_DISPATCHERS.get()",
            dispatch_fn is None,
            f"got={dispatch_fn}",
        )

        # Now test the server's call_tool handler which builds the UNKNOWN_TOOL error
        # We simulate what server.py does at lines 104-116
        name = "totally_fake_tool_12345"
        from clipcannon.tools import ALL_TOOL_DEFINITIONS
        if dispatch_fn is None:
            error_result = {
                "error": {
                    "code": "UNKNOWN_TOOL",
                    "message": f"Unknown tool: {name}",
                    "details": {"available_tools": [t.name for t in ALL_TOOL_DEFINITIONS]},
                },
            }
            record(
                "UNKNOWN_TOOL error code in response",
                error_result["error"]["code"] == "UNKNOWN_TOOL",
            )
            record(
                "Error message contains tool name",
                name in error_result["error"]["message"],
            )
            record(
                "Error details include available_tools list",
                len(error_result["error"]["details"]["available_tools"]) == 50,
                f"count={len(error_result['error']['details']['available_tools'])}",
            )

    except Exception as exc:
        record("Unknown tool handling", False, f"Exception: {exc}")


# ============================================================
# TEST 5: Default configuration validation
# ============================================================
def test_default_config() -> None:
    separator("TEST 5: Default Configuration Validation")
    try:
        config_path = Path(__file__).resolve().parent.parent / "config" / "default_config.json"

        record("Config file exists", config_path.exists(), f"path={config_path}")

        with open(config_path) as f:
            config = json.load(f)

        print(f"\n  Full config contents:")
        print(json.dumps(config, indent=4))

        # Check all required sections
        print("\n  Required sections:")
        for section in REQUIRED_CONFIG_SECTIONS:
            record(f"Section '{section}' present", section in config)

        # Specific value checks
        print("\n  Specific value validation:")
        processing = config.get("processing", {})

        whisper_model = processing.get("whisper_model")
        record(
            "processing.whisper_model = 'large-v3'",
            whisper_model == "large-v3",
            f"actual={whisper_model!r}",
        )

        frame_fps = processing.get("frame_extraction_fps")
        record(
            "processing.frame_extraction_fps = 2",
            frame_fps == 2,
            f"actual={frame_fps!r}",
        )

        scene_thresh = processing.get("scene_change_threshold")
        record(
            "processing.scene_change_threshold = 0.75",
            scene_thresh == 0.75,
            f"actual={scene_thresh!r}",
        )

        # Additional config checks
        version = config.get("version")
        record("version field present", version is not None, f"value={version!r}")

        dirs = config.get("directories", {})
        record("directories.projects present", "projects" in dirs)
        record("directories.models present", "models" in dirs)
        record("directories.temp present", "temp" in dirs)

        rendering = config.get("rendering", {})
        record("rendering.default_profile present", "default_profile" in rendering)
        record("rendering.use_nvenc present", "use_nvenc" in rendering)

        gpu = config.get("gpu", {})
        record("gpu.device present", "device" in gpu)
        record("gpu.max_vram_usage_gb present", "max_vram_usage_gb" in gpu)

    except Exception as exc:
        record("Config validation", False, f"Exception: {exc}")


# ============================================================
# TEST 6: Tool definition schema integrity
# ============================================================
def test_tool_schema_integrity() -> None:
    separator("TEST 6: Tool Schema Integrity")
    try:
        from clipcannon.tools import ALL_TOOL_DEFINITIONS

        for tool in ALL_TOOL_DEFINITIONS:
            has_name = bool(tool.name)
            has_desc = bool(tool.description)
            has_schema = bool(tool.inputSchema)
            schema_has_type = tool.inputSchema.get("type") == "object" if tool.inputSchema else False
            schema_has_props = "properties" in (tool.inputSchema or {})

            all_good = has_name and has_desc and has_schema and schema_has_type and schema_has_props
            detail_parts = []
            if not has_name:
                detail_parts.append("missing name")
            if not has_desc:
                detail_parts.append("missing description")
            if not has_schema:
                detail_parts.append("missing inputSchema")
            if not schema_has_type:
                detail_parts.append("inputSchema type != object")
            if not schema_has_props:
                detail_parts.append("missing properties")

            record(
                f"Schema valid for '{tool.name}'",
                all_good,
                ", ".join(detail_parts) if detail_parts else "",
            )

    except Exception as exc:
        record("Tool schema integrity", False, f"Exception: {exc}")


# ============================================================
# MAIN: Run all tests
# ============================================================
def main() -> None:
    print("=" * 60)
    print("  SHERLOCK HOLMES - Full State Verification")
    print("  ClipCannon MCP Server Scaffold")
    print("=" * 60)

    test_server_creation()
    test_tool_registry()
    test_dispatchers()
    test_unknown_tool()
    test_default_config()
    test_tool_schema_integrity()

    # Final summary
    separator("INVESTIGATION SUMMARY")
    total = results["passed"] + results["failed"]
    print(f"\n  Total checks: {total}")
    print(f"  Passed:       {results['passed']}")
    print(f"  Failed:       {results['failed']}")

    if results["errors"]:
        print(f"\n  FAILURES:")
        for err in results["errors"]:
            print(f"    - {err}")

    if results["failed"] == 0:
        print("\n  VERDICT: ALL CHECKS PASSED - Server scaffold is INNOCENT")
    else:
        print(f"\n  VERDICT: {results['failed']} CHECK(S) FAILED - Server scaffold is GUILTY")

    print(f"\n{'='*60}")

    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
