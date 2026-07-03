"""
Email.py
Sends a monthly HTML summary email of all DinosaurList tool updates.

Reads every {ToolName}_{Version}_{Developer}.md file from data/ and
composes a formatted HTML email listing each tool's ## Update List content.

Configuration — edit Email.json at the project root:
  smtp_host     SMTP relay host
  smtp_port     SMTP port
  smtp_tls      true to use SMTP_SSL
  smtp_user     Login user (if required)
  smtp_pass     Login password (if required)
  sender        From address
  recipients    List of To addresses

Run directly:   python src/lib/Email.py
Schedule:       First day of each month (Task Scheduler / cron).
Dry-run:        python src/main.py --dry-run   (writes HTML preview, no send)
"""

import json
import re
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path

PROJECT_ROOT  = Path(__file__).parent.parent.parent
DATA_DIR      = PROJECT_ROOT / "data"
UPDATE_RECORD = PROJECT_ROOT / "UpdateRecord.json"

# ── Load Email.json ───────────────────────────────────────────────────────────
_cfg_path = PROJECT_ROOT / "Email.json"
if not _cfg_path.exists():
    print(f"[ERROR] Email.json not found at {_cfg_path}")
    sys.exit(1)

try:
    _text = _cfg_path.read_text(encoding="utf-8").strip()
    if not _text:
        print(f"[ERROR] Email.json is empty: {_cfg_path}")
        sys.exit(1)
    _cfg = json.loads(_text)
except json.JSONDecodeError as _exc:
    print(f"[ERROR] Email.json is not valid JSON ({_exc}): {_cfg_path}")
    sys.exit(1)

SMTP_HOST    = _cfg.get("smtp_host", "mailrelay.broadcom.com")
SMTP_PORT    = int(_cfg.get("smtp_port", 25))
SMTP_USE_TLS = bool(_cfg.get("smtp_tls", False))
SMTP_USER    = _cfg.get("smtp_user", "")
SMTP_PASS    = _cfg.get("smtp_pass", "")
SENDER       = _cfg.get("sender", "")
RECIPIENTS   = [r.strip() for r in _cfg.get("recipients", []) if r.strip()]


# ── Read UpdateRecord.json and decide what to email ───────────────────────────

def _load_tools() -> tuple[list[dict], list[dict]]:
    """Return (updated_tools, all_tools) from UpdateRecord.json.

    updated_tools: tools whose version differs from last_emailed_version,
                   meaning they have a new release since the last email.
                   On the very first execution of the pipeline
                   (email_send_count == 1), every tool is treated as updated
                   so the first email always includes full content for the
                   whole DinosaurList; from the second execution onward
                   (email_send_count > 1) diff-based tracking takes over.
    """
    if not UPDATE_RECORD.exists():
        return [], []
    try:
        text = UPDATE_RECORD.read_text(encoding="utf-8").strip()
        if not text:
            print(f"[ERROR] UpdateRecord.json is empty: {UPDATE_RECORD}")
            return [], []
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] UpdateRecord.json is not valid JSON ({exc}): {UPDATE_RECORD}")
        return [], []
    all_tools = record.get("tools", [])
    if record.get("email_send_count", 0) <= 1:
        return list(all_tools), all_tools
    updated = [
        t for t in all_tools
        if t.get("version") != t.get("last_emailed_version")
    ]
    return updated, all_tools


def _mark_emailed(updated_tools: list[dict]) -> None:
    """Stamp last_emailed_version = version for every tool that was just emailed."""
    if not UPDATE_RECORD.exists() or not updated_tools:
        return
    try:
        text = UPDATE_RECORD.read_text(encoding="utf-8").strip()
        if not text:
            return
        record = json.loads(text)
    except json.JSONDecodeError:
        return
    stamped = {t["folder_name"] for t in updated_tools}
    for tool in record.get("tools", []):
        if tool["folder_name"] in stamped:
            tool["last_emailed_version"] = tool["version"]
    with open(UPDATE_RECORD, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)


# ── Read extracted update files ───────────────────────────────────────────────

def _read_update_files(updated_tools: list[dict]) -> list[dict]:
    """Parse .md files only for tools that have a new version to email."""
    entries = []
    for tool in updated_tools:
        md_file = DATA_DIR / tool["extracted_file"]
        if not md_file.exists():
            continue

        lines = md_file.read_text(encoding="utf-8").splitlines()

        # Line 0:  # ToolName — Update List
        # Line 1:  Version: X.X.X.X  |  Developer: Name
        # Line 2:  (blank)
        # Line 3+: update content
        title        = lines[0].lstrip("# ").strip() if lines else md_file.stem
        version_line = lines[1].strip()              if len(lines) > 1 else ""
        content      = "\n".join(lines[3:]).strip()  if len(lines) > 3 else ""

        if not content or content == "(No update entries found)":
            continue

        entries.append({
            "title":        title,
            "version_line": version_line,
            "content":      content,
        })
    return entries


# ── Build HTML email ──────────────────────────────────────────────────────────

def _content_to_html_items(content: str) -> tuple[str, bool]:
    """Return (html <li> items, is_ordered).

    is_ordered is True when every line starts with N) — caller uses <ol> so the
    browser renders native numbers with no extra bullet dot.
    """
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    is_ordered = bool(lines) and all(re.match(r"^\d+[.)]\s", l) for l in lines)
    html = ""
    for line in lines:
        text = re.sub(r"^(\d+[.)]|[-*])\s+", "", line)
        html += f"        <li>{text}</li>\n"
    return html or "        <li>(No entries)</li>\n", is_ordered


def _build_html_no_updates(all_tools: list[dict], month_label: str) -> str:
    tool_rows = "".join(
        f"    <li>{t['tool_name']} &nbsp;<span class='ver'>v{t['version']}</span>"
        f" &mdash; {t['developer_name']}</li>\n"
        for t in all_tools
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    body    {{ font-family: Arial, sans-serif; color: #2d2d2d;
              max-width: 740px; margin: 40px auto; padding: 0 20px; }}
    h1      {{ color: #1a56a0; border-bottom: 2px solid #1a56a0;
              padding-bottom: 8px; font-size: 1.4em; }}
    .banner {{ background: #eaf6ea; border-left: 4px solid #2e8b2e;
              padding: 14px 18px; border-radius: 4px; margin-bottom: 18px; }}
    .banner p {{ margin: 0; font-size: 1em; color: #1e5c1e; font-weight: bold; }}
    ul      {{ margin: 6px 0 0; padding-left: 20px; }}
    li      {{ margin-bottom: 4px; font-size: 0.93em; }}
    .ver    {{ color: #888; font-size: 0.88em; }}
    .footer {{ font-size: 0.78em; color: #999; border-top: 1px solid #ddd;
              padding-top: 12px; margin-top: 28px; }}
  </style>
</head>
<body>
  <h1>DinosaurList &#x1F9B8; — Monthly Tool Update ({month_label})</h1>
  <div class="banner">
    <p>&#x2705; No updates this month — all {len(all_tools)} tool(s) are up to date.</p>
  </div>
  <p>Current tools in the App Store:</p>
  <ul>
{tool_rows}  </ul>
  <div class="footer">
    This is an automated monthly summary from <strong>DinosaurList App Store</strong>.<br>
    For questions, please contact the respective tool developer directly.
  </div>
</body>
</html>"""


def _build_html(entries: list[dict], month_label: str) -> str:
    tool_blocks = ""
    for e in entries:
        items_html, is_ordered = _content_to_html_items(e["content"])
        list_tag = "ol" if is_ordered else "ul"
        tool_blocks += f"""
  <div class="tool">
    <h3>{e['title']}</h3>
    <p class="meta">{e['version_line']}</p>
    <{list_tag}>
{items_html}    </{list_tag}>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    body      {{ font-family: Arial, sans-serif; color: #2d2d2d;
                max-width: 740px; margin: 40px auto; padding: 0 20px; }}
    h1        {{ color: #1a56a0; border-bottom: 2px solid #1a56a0;
                padding-bottom: 8px; font-size: 1.4em; }}
    h3        {{ color: #1e5c1e; margin: 0 0 4px; font-size: 1em; }}
    .tool     {{ background: #f6f8fc; border-left: 4px solid #1a56a0;
                padding: 12px 18px; margin-bottom: 14px; border-radius: 4px; }}
    .meta     {{ color: #666; font-size: 0.82em; margin: 0 0 8px; }}
    ul        {{ margin: 0; padding-left: 20px; }}
    li        {{ margin-bottom: 3px; font-size: 0.93em; }}
    .footer   {{ font-size: 0.78em; color: #999; border-top: 1px solid #ddd;
                padding-top: 12px; margin-top: 28px; }}
  </style>
</head>
<body>
  <h1>DinosaurList &#x1F9B8; — Monthly Tool Update ({month_label})</h1>
  <p>Below are the latest updates from tools published in the WSD DinosaurList App Store.</p>
  {tool_blocks}
  <div class="footer">
    This is an automated monthly summary from <strong>DinosaurList App Store</strong>.<br>
    For questions, please contact the respective tool developer directly.
  </div>
</body>
</html>"""


# ── Send ──────────────────────────────────────────────────────────────────────

def send_email(dry_run: bool = False) -> None:
    updated_tools, all_tools = _load_tools()

    if not all_tools:
        print("[WARN] UpdateRecord.json is empty or missing.")
        print("       Run Steps 1 & 2 first, then retry.")
        return

    if not RECIPIENTS and not dry_run:
        print("[ERROR] No recipients configured in Email.json.")
        sys.exit(1)

    month_label = datetime.now().strftime("%B %Y")

    if not updated_tools:
        print(f"[INFO] No tools have new versions — sending 'all good' email.")
        html_body = _build_html_no_updates(all_tools, month_label)
        subject   = f"[DinosaurList] Monthly Tool Update — {month_label} (No Changes)"
        entries   = []
    else:
        entries   = _read_update_files(updated_tools)
        html_body = _build_html(entries, month_label)
        subject   = f"[DinosaurList] Monthly Tool Update — {month_label}"

    if dry_run:
        preview = PROJECT_ROOT / "_email_preview.html"
        preview.write_text(html_body, encoding="utf-8")
        print(f"[DRY-RUN] HTML preview written to {preview}")
        print(f"[DRY-RUN] Subject : {subject}")
        if entries:
            print(f"[DRY-RUN] Updated : {len(entries)} tool(s)")
            for e in entries:
                print(f"           • {e['title']}  ({e['version_line']})")
        else:
            print(f"[DRY-RUN] No changes — {len(all_tools)} tool(s) all up to date.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"[INFO] Sending '{subject}' to {len(RECIPIENTS)} recipient(s) ...")
    try:
        if SMTP_USE_TLS and SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.ehlo()
            if SMTP_USE_TLS:
                server.starttls()
                server.ehlo()

        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)

        server.sendmail(SENDER, RECIPIENTS, msg.as_string())
        server.quit()
        print("[OK] Email sent successfully.")
        _mark_emailed(updated_tools)
    except Exception as exc:
        print(f"[ERROR] Failed to send email: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    dry_run_flag = "--dry-run" in sys.argv
    send_email(dry_run=dry_run_flag)
