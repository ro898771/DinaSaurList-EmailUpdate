"""
main.py  —  DinosaurList Monthly Update Pipeline
Wires the three modules in the correct dependency order:

  Step 1  UpdateRecord.py  — scan config-record/record.json and build
                             email-dev/UpdateRecord.json (version metadata).
  Step 2  UpdateExtract.py — download READMEs from Box and extract each
                             ## Update List into email-dev/data/*.md.
  Step 3  Email.py         — compose and send the monthly HTML update email.

Run:
  python email-dev/main.py               # full pipeline
  python email-dev/main.py --force       # re-fetch all READMEs even if current
  python email-dev/main.py --dry-run     # build files but preview email, no send
  python email-dev/main.py --skip-email  # steps 1 & 2 only, no email
"""

import sys
from pathlib import Path

# Make sure imports work regardless of the working directory
sys.path.insert(0, str(Path(__file__).parent))

import lib.UpdateRecord as UpdateRecord
import lib.UpdateExtract as UpdateExtract
import lib.Email as Email

UPDATE_RECORD = Path(__file__).parent.parent / "UpdateRecord.json"


def main() -> None:
    force      = "--force"      in sys.argv
    dry_run    = "--dry-run"    in sys.argv
    skip_email = "--skip-email" in sys.argv

    # ── Step 1: Refresh UpdateRecord.json ────────────────────────────────────
    print("=" * 60)
    print("  STEP 1 — Refresh UpdateRecord.json")
    print("=" * 60)
    step1_ok = UpdateRecord.build_update_record()

    if not step1_ok:
        sys.exit(1)

    # ── Step 2: Download & extract ## Update List sections ───────────────────
    print()
    print("=" * 60)
    print("  STEP 2 — Extract Update Lists from Box READMEs")
    print("=" * 60)
    UpdateExtract.run(force=force)

    if skip_email:
        print("\n[INFO] --skip-email flag set. Pipeline complete (no email sent).")
        return

    # ── Step 3: Send monthly update email ────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 3 — Send Monthly Update Email")
    print("=" * 60)
    Email.send_email(dry_run=dry_run)

    print()
    print("=" * 60)
    print("  Pipeline complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
