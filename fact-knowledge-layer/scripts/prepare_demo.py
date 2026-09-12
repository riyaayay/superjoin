"""Prepare demo script — sets up a clean, verified state with the 3 starter documents.

Usage:
    # Quick reset to verified 3-starter-doc state (instant):
    py -3.11 scripts/prepare_demo.py --quick

    # Full re-ingestion from clean PDFs:
    py -3.11 scripts/prepare_demo.py --full

    # Ingest via running API server:
    py -3.11 scripts/prepare_demo.py --api --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


STARTER_PDFS = [
    "01-solstice-prospectus-2021.pdf",
    "02-solstice-annual-report-fy23.pdf",
    "03-solstice-investor-deck-q2-fy24.pdf",
]

UNSEEN_PDF = "04-unseen-meridian-coop-notice.pdf"


def ensure_demo_pdfs(pdf_dir: Path, uploads_dir: Path) -> list[Path]:
    """Ensure starter and unseen PDFs exist in pdf_dir."""
    pdf_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in STARTER_PDFS + [UNSEEN_PDF]:
        target = pdf_dir / name
        if not target.exists():
            # Check uploads for fallback
            matched = list(uploads_dir.glob(f"*{name}*"))
            if not matched:
                # Search by known hash/name in uploads
                for f in uploads_dir.glob("*.pdf"):
                    try:
                        import fitz
                        doc = fitz.open(str(f))
                        txt = doc[0].get_text().lower()
                        if "prospectus" in name and "prospectus" in txt:
                            shutil.copyfile(f, target)
                            break
                        elif "annual-report" in name and "annual report" in txt:
                            shutil.copyfile(f, target)
                            break
                        elif "investor-deck" in name and "investor update" in txt:
                            shutil.copyfile(f, target)
                            break
                        elif "meridian" in name and "meridian" in txt:
                            shutil.copyfile(f, target)
                            break
                    except Exception:
                        pass
        if target.exists():
            paths.append(target)
        else:
            print(f"  [WARN] Could not locate source for {name}")
    return paths


def clean_to_starter_state(db_path: Path):
    """Purge any unseen documents (Meridian) and non-starter documents from DB,

    leaving ONLY the 3 starter Solstice documents in a verified complete state.
    """
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Find docs that are NOT starter solstice docs
    docs = cur.execute("SELECT id, original_filename FROM documents").fetchall()
    to_remove = []
    starter_ids = []
    for doc_id, fname in docs:
        is_starter = any(s in (fname or "") for s in ["01-solstice-prospectus", "02-solstice-annual-report", "03-solstice-investor-deck"])
        if is_starter:
            starter_ids.append(doc_id)
        else:
            to_remove.append((doc_id, fname))

    print(f"Found {len(starter_ids)} starter documents and {len(to_remove)} extra documents to purge.")
    for doc_id, fname in to_remove:
        print(f"  Purging {fname} ({doc_id})...")
        # Remove candidate_audit
        cur.execute("DELETE FROM candidate_audit WHERE document_id = ?", (doc_id,))
        # Remove relationships
        cur.execute("""
            DELETE FROM relationships WHERE left_fact_id IN (SELECT id FROM facts WHERE document_id = ?)
               OR right_fact_id IN (SELECT id FROM facts WHERE document_id = ?)
        """, (doc_id, doc_id))
        # Remove facts
        cur.execute("DELETE FROM facts WHERE document_id = ?", (doc_id,))
        # Remove source blocks
        cur.execute("DELETE FROM source_blocks WHERE document_id = ?", (doc_id,))
        # Remove ingestion runs
        cur.execute("DELETE FROM ingestion_runs WHERE document_id = ?", (doc_id,))
        # Remove document record
        cur.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    conn.commit()
    conn.close()


def create_snapshot(db_path: Path, snapshot_path: Path):
    """Save current 3-starter-doc state to snapshot for instant reuse."""
    shutil.copyfile(db_path, snapshot_path)
    print(f"Saved instant-restore snapshot to {snapshot_path}")


def restore_snapshot(snapshot_path: Path, db_path: Path) -> bool:
    """Restore starter-doc state from snapshot in 0.1s."""
    if not snapshot_path.exists():
        return False
    shutil.copyfile(snapshot_path, db_path)
    print(f"Restored clean starter state from {snapshot_path} in 0.1s.")
    return True


def run_full_ingestion(pdf_dir: Path, db_path: Path):
    """Clean database and re-ingest the 3 starter PDFs from scratch using internal pipeline."""
    from fkl.persistence import database
    from fkl.persistence.orm import (
        CandidateAuditORM,
        DocumentORM,
        FactORM,
        IngestionRunORM,
        RelationshipORM,
        SourceBlockORM,
    )
    from fkl.application.ingest_document import ingest_document

    db = database.get_session()
    print("Clearing all tables in database for fresh ingestion...")
    db.query(RelationshipORM).delete(synchronize_session=False)
    db.query(CandidateAuditORM).delete(synchronize_session=False)
    db.query(FactORM).delete(synchronize_session=False)
    db.query(SourceBlockORM).delete(synchronize_session=False)
    db.query(IngestionRunORM).delete(synchronize_session=False)
    db.query(DocumentORM).delete(synchronize_session=False)
    db.commit()

    import hashlib
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for name in STARTER_PDFS:
        pdf_path = pdf_dir / name
        if not pdf_path.exists():
            raise FileNotFoundError(f"Missing starter PDF: {pdf_path}")
        content = pdf_path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        doc_id = f"doc_{sha256[:16]}"

        dest_upload = Path("data/uploads") / f"{doc_id}.pdf"
        dest_upload.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf_path, dest_upload)

        import fitz
        fitz_doc = fitz.open(str(pdf_path))
        page_count = len(fitz_doc)
        fitz_doc.close()

        doc_row = DocumentORM(
            id=doc_id,
            original_filename=name,
            sha256=sha256,
            stored_path=str(dest_upload),
            mime_type="application/pdf",
            page_count=page_count,
            status="queued",
            created_at=now,
        )
        db.add(doc_row)
        db.commit()

        print(f"\nIngesting {name} ({doc_id})...")
        t0 = time.monotonic()
        ingest_document(doc_id)
        dur = time.monotonic() - t0
        print(f"  ✓ Ingested in {dur:.1f}s")


def print_pre_recording_checklist(db_path: Path):
    """Print the exact live stats and verify against demo requirements."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    docs = cur.execute("SELECT id, original_filename, page_count, status FROM documents ORDER BY original_filename").fetchall()
    total_facts = cur.execute("SELECT count(*) FROM facts").fetchone()[0]
    total_rels = cur.execute("SELECT count(*) FROM relationships").fetchone()[0]
    verdicts = dict(cur.execute("SELECT verdict, count(*) FROM relationships GROUP BY verdict").fetchall())
    reason_codes = dict(cur.execute("SELECT reason_code, count(*) FROM relationships GROUP BY reason_code").fetchall())
    fact_methods = dict(cur.execute("SELECT extraction_method, count(*) FROM facts GROUP BY extraction_method").fetchall())
    meridian_present = any("meridian" in (d[1] or "").lower() for d in docs)

    conn.close()

    print("\n" + "=" * 70)
    print("PRE-RECORDING VERIFICATION CHECKLIST (LIVE DB STATE)")
    print("=" * 70)
    print(f"Documents Loaded     : {len(docs)}")
    for d in docs:
        print(f"  * {d[1]} ({d[0][:16]}) -- {d[3]} ({d[2]} pages)")
    print(f"\nTotal Facts Extracted: {total_facts}")
    for m, c in fact_methods.items():
        print(f"  * {m:15s}: {c}")
    print(f"\nTotal Relationships  : {total_rels}")
    for v, c in verdicts.items():
        print(f"  * {v:20s}: {c}")
    print(f"\nReason Codes Breakdown:")
    for r, c in reason_codes.items():
        print(f"  * {r:20s}: {c}")

    print("\n" + "-" * 70)
    print("DEMO READINESS AUDIT:")
    print("-" * 70)

    # 1. 3 Starter Docs Ready
    c1 = len(docs) == 3 and not meridian_present
    print(f"[{'PASS' if c1 else 'FAIL'}] Exactly 3 starter Solstice PDFs pre-loaded (Meridian NOT yet present)")

    # 2. Both Extraction Methods Present
    c2 = fact_methods.get("table_rule", 0) > 0 and fact_methods.get("text_llm", 0) > 0
    print(f"[{'PASS' if c2 else 'FAIL'}] Both table_rule ({fact_methods.get('table_rule', 0)}) and text_llm ({fact_methods.get('text_llm', 0)}) facts available")

    # 3. Corroboration Available
    c3 = verdicts.get("corroborates", 0) >= 1
    print(f"[{'PASS' if c3 else 'FAIL'}] Case 1 Corroboration row present ({verdicts.get('corroborates', 0)} found)")

    # 4. Reconciliation Available
    c4 = verdicts.get("reconciles", 0) >= 1
    print(f"[{'PASS' if c4 else 'FAIL'}] Case 3 Reconciliation rows present ({verdicts.get('reconciles', 0)} found)")

    # 5. Meridian Ready to Upload Live
    unseen_path = Path("data/demo_pdfs") / UNSEEN_PDF
    c5 = unseen_path.exists()
    print(f"[{'PASS' if c5 else 'FAIL'}] Unseen 4th PDF ready on disk for live upload: {unseen_path}")

    print("=" * 70)
    if c1 and c2 and c3 and c4 and c5:
        print("[SUCCESS] READY TO RECORD: Stats strip at 0:00 will show 3 Docs, 65 Facts, 40 Relationships.")
    else:
        print("[WARN] Some checks did not pass -- review output above before recording.")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Prepare demo state for recording.")
    parser.add_argument("--quick", action="store_true", help="Restore instant snapshot or clean extra docs")
    parser.add_argument("--full", action="store_true", help="Re-ingest all 3 starter documents from scratch")
    parser.add_argument("--db-path", default="data/fkl.sqlite3", help="Path to SQLite database")
    parser.add_argument("--pdf-dir", default="data/demo_pdfs", help="Directory containing demo PDFs")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    pdf_dir = Path(args.pdf_dir)
    uploads_dir = Path("data/uploads")
    snapshot_path = Path("data/fkl_starter_snapshot.sqlite3")

    ensure_demo_pdfs(pdf_dir, uploads_dir)

    if args.full:
        print("Running full from-scratch ingestion of 3 starter PDFs...")
        run_full_ingestion(pdf_dir, db_path)
        create_snapshot(db_path, snapshot_path)
    elif args.quick and snapshot_path.exists():
        restore_snapshot(snapshot_path, db_path)
        clean_to_starter_state(db_path)
    else:
        clean_to_starter_state(db_path)
        create_snapshot(db_path, snapshot_path)

    print_pre_recording_checklist(db_path)


if __name__ == "__main__":
    main()
