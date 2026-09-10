"""Documents API router — upload, status, page rendering."""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from fkl.api.deps import get_db
from fkl.application.ingest_document import ingest_document
from fkl.config import get_settings
from fkl.persistence import repositories

router = APIRouter(prefix="/api/documents", tags=["documents"])

_PDF_MAGIC = b"%PDF"


def _sha256_path(pdf_path: Path) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_pdf(data: bytes) -> None:
    if not data[:4] == _PDF_MAGIC:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")


@router.post("")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    # Read and validate
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB limit.")
    _validate_pdf(data)

    # Compute SHA-256 for deduplication
    sha256 = hashlib.sha256(data).hexdigest()

    # Check for duplicate
    existing = repositories.get_document_by_sha(db, sha256)
    if existing:
        stats = repositories.get_document_stats(db, existing.id)
        return {
            "document_id": existing.id,
            "status": existing.status,
            "deduplicated": True,
            "original_filename": existing.original_filename,
            "stats": stats,
        }

    # Store with UUID filename (never user-provided filename)
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"
    stored_name = f"{doc_id}.pdf"
    stored_path = settings.upload_dir / stored_name
    stored_path.write_bytes(data)

    # Create DB record
    repositories.create_document(
        db,
        id=doc_id,
        original_filename=file.filename or "unknown.pdf",
        sha256=sha256,
        stored_path=str(stored_path),
        mime_type="application/pdf",
        status="queued",
    )

    # Kick off background ingestion
    background_tasks.add_task(ingest_document, doc_id)

    return {"document_id": doc_id, "status": "queued", "deduplicated": False}


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    docs = repositories.list_documents(db)
    return [
        {
            "document_id": d.id,
            "original_filename": d.original_filename,
            "status": d.status,
            "page_count": d.page_count,
            "canonical_entity": d.canonical_entity,
            "created_at": d.created_at,
            "completed_at": d.completed_at,
            "error_message": d.error_message,
        }
        for d in docs
    ]


@router.get("/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = repositories.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    stats = repositories.get_document_stats(db, document_id)
    runs = [
        {
            "run_id": r.id,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "facts_created": r.facts_created,
            "facts_rejected": r.facts_rejected,
            "relationships_created": r.relationships_created,
            "insufficient_context_count": getattr(r, "insufficient_context_count", 0),
            "blocks_skipped_due_to_cap": getattr(r, "blocks_skipped_due_to_cap", 0),
            "prose_blocks_total": getattr(r, "prose_blocks_total", 0),
            "prose_blocks_llm_called": getattr(r, "prose_blocks_llm_called", 0),
            "table_cells_total": getattr(r, "table_cells_total", 0),
            "table_cells_rejected_missing_header": getattr(r, "table_cells_rejected_missing_header", 0),
            "table_cells_rejected_not_numeric": getattr(r, "table_cells_rejected_not_numeric", 0),
            "relationship_pairs_total": getattr(r, "relationship_pairs_total", 0),
            "relationship_pairs_jaccard_matched": getattr(r, "relationship_pairs_jaccard_matched", 0),
            "relationship_pairs_llm_fallback_matched": getattr(r, "relationship_pairs_llm_fallback_matched", 0),
            "relationship_pairs_insufficient_context": getattr(r, "relationship_pairs_insufficient_context", 0),
            "relationships_error": getattr(r, "relationships_error", None),
        }
        for r in doc.runs
    ]
    return {
        "document_id": doc.id,
        "original_filename": doc.original_filename,
        "status": doc.status,
        "page_count": doc.page_count,
        "canonical_entity": doc.canonical_entity,
        "created_at": doc.created_at,
        "completed_at": doc.completed_at,
        "error_message": doc.error_message,
        "stats": stats,
        "runs": runs,
    }


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    deleted = repositories.delete_document(db, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "ok", "deleted": True, "document_id": document_id}


@router.get("/{document_id}/pages/{page_index}")
def get_page_render(document_id: str, page_index: int, db: Session = Depends(get_db)):
    """Render a PDF page as PNG and return it."""
    import fitz

    settings = get_settings()
    doc = repositories.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    render_path = settings.render_dir / f"{document_id}_p{page_index}.png"
    if not render_path.exists():
        try:
            pdf = fitz.open(doc.stored_path)
            if page_index < 1 or page_index > len(pdf):
                raise HTTPException(status_code=404, detail=f"Page {page_index} out of range")
            page = pdf[page_index - 1]
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for legibility
            pix = page.get_pixmap(matrix=mat)
            pix.save(str(render_path))
            pdf.close()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Render failed: {e}")

    return FileResponse(str(render_path), media_type="image/png")
