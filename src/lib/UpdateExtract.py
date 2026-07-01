"""
UpdateExtract.py
Downloads README.md files from Box and extracts the ## Update List section.

Decision logic:
  - email-dev/ has NO .md files  ->  fetch ALL tools from Box.
  - email-dev/ already has files ->  fetch only tools where is_latest=False
                                      in UpdateRecord.json.

Each extracted file is saved as:
    email-dev/{ToolName}_{Version}_{Developer}.md

UpdateRecord.json is refreshed on completion.

Run directly:  python email-dev/UpdateExtract.py
               python email-dev/UpdateExtract.py --force   (re-fetch everything)
"""

import sys
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT  = Path(__file__).parent.parent.parent
DATA_DIR      = PROJECT_ROOT / "data"
UPDATE_RECORD = PROJECT_ROOT / "UpdateRecord.json"

# Extend path so src/lib imports work when called from any directory
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lib.boxlink_api import BoxLinkAPI  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_update_list(readme_text: str) -> str:
    """Return the content under ## Update List, stripping all other sections."""
    lines      = readme_text.splitlines()
    in_section = False
    collected  = []

    for line in lines:
        stripped = line.strip()
        if stripped.lower() == "## update list":
            in_section = True
            continue
        if in_section:
            # Stop at next heading or horizontal rule
            if stripped.startswith("## ") or stripped == "---":
                break
            collected.append(line)

    content = "\n".join(collected).strip()
    return content if content else "(No update entries found)"


def _write_extracted_file(tool_name: str, version: str, developer: str, out_path: Path, content: str) -> None:
    """Remove any stale version .md for this tool, then write the new one."""
    prefix = f"{tool_name}_"
    suffix = f"_{developer}.md"
    for old in DATA_DIR.iterdir():
        if old.is_file() and old.name.startswith(prefix) and old.name.endswith(suffix) and old != out_path:
            old.unlink()
            print(f"  [CLEAN] Removed old: {old.name}")

    out_path.write_text(
        f"# {tool_name} — Update List\n"
        f"Version: {version}  |  Developer: {developer}\n\n"
        f"{content}\n",
        encoding="utf-8",
    )


def _existing_md_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return list(DATA_DIR.glob("*.md"))


def _load_record() -> dict:
    if not UPDATE_RECORD.exists():
        return {}
    try:
        text = UPDATE_RECORD.read_text(encoding="utf-8").strip()
        if not text:
            print(f"[ERROR] UpdateRecord.json is empty: {UPDATE_RECORD}")
            return {}
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] UpdateRecord.json is not valid JSON ({exc}): {UPDATE_RECORD}")
        return {}


def _save_record(record: dict) -> None:
    record["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(UPDATE_RECORD, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(force: bool = False) -> bool:
    try:
        api = BoxLinkAPI(PROJECT_ROOT / "BoxLink-API" / "BoxAutomate.exe")
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    record    = _load_record()
    all_tools = record.get("tools", [])

    if not all_tools:
        print("[ERROR] UpdateRecord.json is empty or missing. Run UpdateRecord.py first.")
        sys.exit(1)

    if force or not _existing_md_files():
        if force:
            print("[INFO] --force flag: re-fetching ALL tools.")
        else:
            print("[INFO] email-dev/data/ is empty — fetching ALL tools.")
        targets = all_tools
    else:
        targets = [t for t in all_tools if not t.get("is_latest", False)]
        print(f"[INFO] {len(targets)} tool(s) pending update (is_latest=False).")

    if not targets:
        print("[OK] All tools are up to date. Nothing to fetch.")
        return True

    # Build a mutable lookup so we can update flags in-place
    tool_map: dict[str, dict] = {t["folder_name"]: t for t in all_tools}
    updated = 0
    failed: list[str] = []

    for tool in targets:
        tool_name  = tool["tool_name"]
        version    = tool["version"]
        developer  = tool["developer_name"]
        readme_id  = tool.get("readme_file_id")
        out_name   = f"{tool_name}_{version}_{developer}.md"
        out_path   = DATA_DIR / out_name

        if not readme_id:
            print(f"  [WARN] {tool_name} — no README.md in Box folder. Writing empty placeholder.")
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _write_extracted_file(tool_name, version, developer, out_path, "(No update entries found)")

            entry = tool_map[tool["folder_name"]]
            entry["is_latest"]      = True
            entry["last_extracted"] = datetime.now(timezone.utc).isoformat()
            updated += 1
            continue

        print(f"  [FETCH] {tool_name} v{version} by {developer} ...", end=" ", flush=True)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            # Pass the directory (not a file path) so BoxAutomate.exe closes the
            # handle cleanly before returning — matching how the GUI app calls it.
            ok, data, err = api.download_dict(readme_id, tmp)

            if not ok or not (data and data.get("downloaded")):
                print(f"FAILED\n    [ERROR] {err or 'download unsuccessful'}")
                failed.append(tool_name)
                continue

            # Resolve the downloaded file: use the destination reported by BoxAutomate
            # only when it points to an actual file (when given a directory it reports
            # the directory itself, not the file inside it).
            dest = data.get("destination")
            if dest and Path(dest).is_file():
                downloaded_path = Path(dest)
            else:
                candidates = [f for f in Path(tmp).iterdir() if f.is_file()]
                if not candidates:
                    print(f"FAILED\n    [ERROR] Downloaded file not found in temp dir")
                    failed.append(tool_name)
                    continue
                downloaded_path = candidates[0]

            readme_text = downloaded_path.read_text(encoding="utf-8", errors="replace")

        update_content = _extract_update_list(readme_text)
        _write_extracted_file(tool_name, version, developer, out_path, update_content)
        print(f"OK -> {out_name}")

        entry = tool_map[tool["folder_name"]]
        entry["is_latest"]      = True
        entry["last_extracted"] = datetime.now(timezone.utc).isoformat()
        updated += 1

    record["tools"] = list(tool_map.values())
    _save_record(record)
    print(f"\n[DONE] {updated} file(s) extracted to email-dev/data/.")

    if failed:
        print(f"[ERROR] {len(failed)} tool(s) failed to extract from Box: {', '.join(failed)}")
        return False
    return True


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    ok = run(force=force_flag)
    if not ok:
        sys.exit(1)
