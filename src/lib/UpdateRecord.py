"""
UpdateRecord.py
Creates and maintains email-dev/UpdateRecord.json.

Scans config-record/record.json for every tool, derives the latest version
from the highest-versioned zip file inside each Box folder, locates the
README.md file ID, and tracks whether the extracted update file is current.

Run directly:  python email-dev/UpdateRecord.py
               python -m email-dev.UpdateRecord   (from project root)
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT  = Path(__file__).parent.parent.parent
DATA_DIR      = PROJECT_ROOT / "data"
UPDATE_RECORD = PROJECT_ROOT / "UpdateRecord.json"

_LOCAL_RECORD = PROJECT_ROOT / "config-record" / "record.json"

# Path to BoxAutomate.exe used for fetching record.json
_BOX_EXE = PROJECT_ROOT / "BoxLink-API" / "BoxAutomate.exe"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_folder_name(folder_name: str) -> tuple[str, str]:
    """Split 'ToolName-DeveloperName' into (tool_name, developer).

    Handles names like:
      BandMaster-SuetLi          -> ('BandMaster', 'SuetLi')
      QuickMi2e-RoeyYee          -> ('QuickMi2e', 'RoeyYee')
      #Python@Deployment-RoeyYee -> ('#Python@Deployment', 'RoeyYee')
      ProductConfigEditor-WanLing-> ('ProductConfigEditor', 'WanLing')

    Falls back to (full_name, 'Unknown') when the pattern does not match.
    """
    # Developer name is the last hyphen-separated token that starts with a capital
    match = re.match(r'^(.+)-([A-Z][a-zA-Z]+)$', folder_name)
    if match:
        return match.group(1), match.group(2)
    return folder_name, "Unknown"


def _latest_version(contents_items: list) -> str:
    """Return the highest version found among vX.Y.Z.W.zip entries."""
    versions = []
    for item in contents_items:
        m = re.match(r'^v(\d+(?:\.\d+)*)\.zip$', item.get("name", ""), re.IGNORECASE)
        if m:
            versions.append(m.group(1))
    if not versions:
        return "Unknown"

    def _key(v: str) -> list:
        parts = [int(x) for x in v.split(".")]
        parts += [0] * (4 - len(parts))
        return parts

    return max(versions, key=_key)


def _find_readme_file_id(contents_items: list) -> str | None:
    """Return the Box file ID for README.md, or None if not present."""
    for item in contents_items:
        if item.get("name", "").lower() == "readme.md":
            return item.get("id")
    return None


# ── Auto-fetch record.json from Box ───────────────────────────────────────────

def _fetch_record_from_box() -> bool:
    """
    Query Box via BoxAutomate.exe to auto-generate config-record/record.json.
    Called automatically by build_update_record() when no record.json is found.
    Returns True on success, False on failure.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    try:
        from lib.boxlink_api import BoxLinkAPI
        api = BoxLinkAPI(_BOX_EXE)
    except FileNotFoundError as exc:
        print(f"[ERROR] Cannot auto-create record.json — BoxAutomate.exe not found: {exc}")
        return False

    print("[INFO] Fetching tool registry from Box (getInfoDefault) ...")
    ok, top, err = api.get_info_default_dict()
    if not ok or not top:
        print(f"[ERROR] Failed to fetch top-level folder from Box: {err}")
        return False

    items_out = []
    for item in top.get("items", []):
        if item.get("type") != "folder":
            continue

        folder_id = item["id"]
        ok2, contents, err2 = api.list_folder_dict(folder_id)
        if not ok2 or not contents:
            print(f"  [WARN] Could not list contents of {item['name']}: {err2}")
            contents = {"folder_id": folder_id, "total_items": 0, "items": []}

        items_out.append({
            "name":        item["name"],
            "type":        item["type"],
            "id":          folder_id,
            "size":        item.get("size"),
            "etag":        item.get("etag"),
            "sequence_id": item.get("sequence_id"),
            "created_at":  item.get("created_at"),
            "modified_at": item.get("modified_at"),
            "created_by":  item.get("created_by"),
            "modified_by": item.get("modified_by"),
            "contents": {
                "folder_id":   contents.get("folder_id", folder_id),
                "total_items": contents.get("total_items", 0),
                "items":       contents.get("items", []),
            },
        })
        print(f"  [OK] {item['name']} — {len(contents.get('items', []))} file(s)")

    if not items_out:
        print("[ERROR] Box returned no tool folders — record.json will not be overwritten.")
        return False

    _LOCAL_RECORD.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "folder_id":  top.get("folder_id"),
        "item_count": len(items_out),
        "items":      items_out,
    }
    with open(_LOCAL_RECORD, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    print(f"[OK] record.json written — {len(items_out)} tool(s).")
    return True


def _load_json(path: Path, label: str) -> dict | None:
    """Read and parse a JSON file, returning None on empty or corrupt file."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            print(f"[ERROR] {label} is empty: {path}")
            return None
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] {label} is not valid JSON ({exc}): {path}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def build_update_record() -> None:
    print("[INFO] Refreshing record.json from Box ...")
    if not _fetch_record_from_box():
        print()
        print("=" * 60)
        print("  FAILED — Could not fetch record.json from Box.")
        print("  Possible causes:")
        print("    • BoxAutomate.exe not found or not accessible")
        print("    • No network / Box connection")
        print("    • Box returned empty folder listing")
        print("  Fix the issue above and re-run the pipeline.")
        print("=" * 60)
        return False

    record = _load_json(_LOCAL_RECORD, "record.json")
    if record is None:
        return False

    # Preserve last_extracted timestamps from a previous run, and bump the
    # execution counter — it increments every time the pipeline runs, so
    # email_send_count == 1 marks the very first execution.
    existing: dict[str, dict] = {}
    email_send_count = 0
    if UPDATE_RECORD.exists():
        saved = _load_json(UPDATE_RECORD, "UpdateRecord.json")
        if saved:
            for t in saved.get("tools", []):
                existing[t["folder_name"]] = t
            email_send_count = saved.get("email_send_count", 0)
    email_send_count += 1

    tools = []
    for item in record.get("items", []):
        folder_name    = item["name"]
        box_folder_id  = item["id"]
        contents_items = item.get("contents", {}).get("items", [])

        tool_name, developer = _parse_folder_name(folder_name)
        version        = _latest_version(contents_items)
        readme_id      = _find_readme_file_id(contents_items)
        extracted_file = f"{tool_name}_{version}_{developer}.md"
        is_latest      = (DATA_DIR / extracted_file).exists()

        prev = existing.get(folder_name, {})
        tools.append({
            "tool_name":           tool_name,
            "version":             version,
            "developer_name":      developer,
            "folder_name":         folder_name,
            "box_folder_id":       box_folder_id,
            "readme_file_id":      readme_id,
            "is_latest":           is_latest,
            "extracted_file":      extracted_file,
            "last_extracted":      prev.get("last_extracted"),
            "last_emailed_version": prev.get("last_emailed_version"),
        })

    # Log tools that disappeared from Box since the previous run
    removed_folders = existing.keys() - {t["folder_name"] for t in tools}
    for folder_name in sorted(removed_folders):
        print(f"  [REMOVED] {folder_name} — no longer present in Box, dropped from UpdateRecord.json")

    # Sweep data/ so it never holds .md files for tools/versions that no longer
    # exist in Box (covers both a whole app being deleted and its content changing).
    valid_extracted_files = {t["extracted_file"] for t in tools}
    if DATA_DIR.exists():
        for md_file in DATA_DIR.glob("*.md"):
            if md_file.name not in valid_extracted_files:
                md_file.unlink()
                print(f"  [CLEAN] Removed orphaned data file: {md_file.name}")

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "email_send_count": email_send_count,
        "tools": tools,
    }
    with open(UPDATE_RECORD, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"[OK] UpdateRecord.json written — {len(tools)} tool(s).")
    for t in tools:
        flag = "[latest] " if t["is_latest"] else "[pending]"
        print(f"  {flag} {t['tool_name']:<35} v{t['version']:<12} by {t['developer_name']}")
    return True


if __name__ == "__main__":
    build_update_record()
