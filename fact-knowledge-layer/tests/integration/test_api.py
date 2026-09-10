"""Integration tests using the FastAPI test client.

Uses a temporary SQLite DB and fake LLM provider.
Covers the main API flows: upload, status, facts, relationships, dedup.
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

import pytest

os.environ["LLM_PROVIDER"] = "fake"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_integration.sqlite3"
os.environ["UPLOAD_DIR"] = "./data/test_uploads"
os.environ["RENDER_DIR"] = "./data/test_renders"


def _make_minimal_pdf(title: str = "India GDP Growth Rate") -> bytes:
    """Create a minimal but valid PDF with real text content for extraction testing."""
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        lines = [
            title,
            "Real GDP growth of the national economy was 6.4% in FY25.",
            "CPI headline inflation rate stood at approximately 4.9% in FY24.",
            "Fiscal deficit for the current year was recorded at 5.1% of GDP.",
        ]
        for line in lines:
            pdf.cell(0, 10, text=line)
            pdf.ln()
        return bytes(pdf.output())
    except Exception:
        # Absolute minimum valid PDF if fpdf2 not installed
        return b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>>>endobj
4 0 obj<</Length 120>>stream
BT /F1 12 Tf 72 720 Td (India GDP growth rate 6.4% FY25) Tj 0 -20 Td (CPI inflation 4.9% FY24) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000274 00000 n
trailer<</Size 5/Root 1 0 R>>
startxref
446
%%EOF"""


@pytest.fixture(scope="module")
def client():
    """FastAPI test client with isolated test database."""
    import tempfile
    import uuid as _uuid
    import fkl.config as cfg

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / f"test_{_uuid.uuid4().hex[:8]}.sqlite3"
        os.environ["LLM_PROVIDER"] = "fake"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        os.environ["UPLOAD_DIR"] = tmpdir
        os.environ["RENDER_DIR"] = tmpdir
        os.environ["GEMINI_API_KEY"] = "fake-key-for-tests"
        cfg._settings = None

        from fastapi.testclient import TestClient
        from fkl.main import create_app
        from fkl.persistence import database as _db

        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

        # Explicitly dispose engine before temp dir cleanup (Windows SQLite lock)
        try:
            _db.init_db.__wrapped__ if hasattr(_db.init_db, '__wrapped__') else None
            if _db._engine:
                _db._engine.dispose()
        except Exception:
            pass


class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestDocumentUpload:
    def test_upload_pdf_returns_document_id(self, client):
        pdf_bytes = _make_minimal_pdf()
        r = client.post(
            "/api/documents",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r.status_code == 200
        data = r.json()
        assert "document_id" in data
        assert data["document_id"].startswith("doc_")

    def test_upload_non_pdf_rejected(self, client):
        r = client.post(
            "/api/documents",
            files={"file": ("test.txt", io.BytesIO(b"not a pdf"), "text/plain")},
        )
        assert r.status_code == 400

    def test_duplicate_upload_deduplicated(self, client):
        pdf_bytes = _make_minimal_pdf()
        r1 = client.post(
            "/api/documents",
            files={"file": ("dup.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r1.status_code == 200
        doc_id1 = r1.json()["document_id"]

        r2 = client.post(
            "/api/documents",
            files={"file": ("dup.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["deduplicated"] is True
        assert data2["document_id"] == doc_id1

    def test_list_documents(self, client):
        r = client.get("/api/documents")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_document_status(self, client):
        pdf_bytes = _make_minimal_pdf()
        r = client.post(
            "/api/documents",
            files={"file": ("status_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        doc_id = r.json()["document_id"]

        r2 = client.get(f"/api/documents/{doc_id}")
        assert r2.status_code == 200
        doc = r2.json()
        assert doc["document_id"] == doc_id
        assert "status" in doc
        assert "stats" in doc

    def test_get_nonexistent_document_404(self, client):
        r = client.get("/api/documents/doc_doesnotexist")
        assert r.status_code == 404

    def test_ingestion_coverage_report(self, client):
        pdf_bytes = _make_minimal_pdf()
        r = client.post(
            "/api/documents",
            files={"file": ("coverage_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r.status_code == 200
        doc_id = r.json()["document_id"]

        r2 = client.get(f"/api/documents/{doc_id}")
        assert r2.status_code == 200
        doc = r2.json()
        assert "runs" in doc
        assert len(doc["runs"]) >= 1

        run0 = doc["runs"][0]
        # Verify all 9 coverage fields are present
        coverage_fields = [
            "prose_blocks_total",
            "prose_blocks_llm_called",
            "table_cells_total",
            "table_cells_rejected_missing_header",
            "table_cells_rejected_not_numeric",
            "relationship_pairs_total",
            "relationship_pairs_jaccard_matched",
            "relationship_pairs_llm_fallback_matched",
            "relationship_pairs_insufficient_context",
        ]
        for field in coverage_fields:
            assert field in run0, f"Missing field {field} in runs[0]"
            assert isinstance(run0[field], int), f"Field {field} is not int"

        # Verify invariants
        assert run0["prose_blocks_llm_called"] <= run0["prose_blocks_total"]
        assert run0["table_cells_rejected_not_numeric"] <= run0["table_cells_total"]
        assert run0["table_cells_rejected_missing_header"] <= run0["table_cells_total"]
        assert (
            run0["relationship_pairs_jaccard_matched"] + run0["relationship_pairs_llm_fallback_matched"]
            <= run0["relationship_pairs_total"]
        )

    def test_fault_isolated_fact_persistence_on_relationship_failure(self, client, monkeypatch):
        from fkl.application import ingest_document as ingest_mod

        def _mock_build_relationships(*args, **kwargs):
            raise RuntimeError("Simulated relationship failure")

        monkeypatch.setattr(ingest_mod, "build_relationships", _mock_build_relationships)

        pdf_bytes = _make_minimal_pdf(title=f"India Fault Isolation Test {uuid.uuid4().hex}")
        r = client.post(
            "/api/documents",
            files={"file": ("rel_fail_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r.status_code == 200
        doc_id = r.json()["document_id"]

        r2 = client.get(f"/api/documents/{doc_id}")
        assert r2.status_code == 200
        doc = r2.json()
        assert doc["status"] == "relationships_failed"
        assert doc["stats"]["facts_accepted"] > 0
        assert len(doc["runs"]) >= 1
        assert doc["runs"][0]["facts_created"] > 0
        assert "Simulated relationship failure" in (doc["runs"][0]["relationships_error"] or "")

        # Assert facts are accessible via facts API
        facts_r = client.get(f"/api/facts?document_id={doc_id}")
        assert facts_r.status_code == 200
        facts_data = facts_r.json()
        assert len(facts_data["items"]) > 0
        assert facts_data["total"] > 0

    def test_solstice_annual_report_end_to_end_regression(self, client):
        fixture_path = Path("tests/fixtures/synthetic/02-solstice-annual-report-fy23.pdf")
        assert fixture_path.exists(), "Fixture 02-solstice-annual-report-fy23.pdf missing"

        pdf_bytes = fixture_path.read_bytes()
        r = client.post(
            "/api/documents",
            files={"file": ("02-solstice-annual-report-fy23.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r.status_code == 200
        doc_id = r.json()["document_id"]

        r2 = client.get(f"/api/documents/{doc_id}")
        assert r2.status_code == 200
        doc = r2.json()
        assert doc["status"] == "complete"
        assert doc["stats"]["facts_accepted"] > 0
        assert len(doc["runs"]) >= 1
        assert doc["runs"][0]["facts_created"] > 0
        assert doc["runs"][0]["relationships_error"] is None

        # Verify facts returned
        facts_r = client.get(f"/api/facts?document_id={doc_id}")
        assert facts_r.status_code == 200
        facts_data = facts_r.json()
        assert facts_data["total"] > 0

    def test_delete_document(self, client):
        pdf_bytes = _make_minimal_pdf()
        r = client.post(
            "/api/documents",
            files={"file": ("to_delete.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r.status_code == 200
        doc_id = r.json()["document_id"]

        # Delete it
        del_r = client.delete(f"/api/documents/{doc_id}")
        assert del_r.status_code == 200
        assert del_r.json()["deleted"] is True

        # Verify it is gone
        get_r = client.get(f"/api/documents/{doc_id}")
        assert get_r.status_code == 404

        # Verify uploading again is not deduplicated
        r2 = client.post(
            "/api/documents",
            files={"file": ("to_delete.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r2.status_code == 200
        assert r2.json()["deduplicated"] is False

    def test_delete_nonexistent_document_404(self, client):
        r = client.delete("/api/documents/doc_doesnotexist")
        assert r.status_code == 404


class TestFactsAPI:
    def test_list_facts_returns_paginated(self, client):
        r = client.get("/api/facts?limit=10&page=1")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_list_facts_with_filters(self, client):
        r = client.get("/api/facts?review_state=accepted&limit=10")
        assert r.status_code == 200

    def test_get_nonexistent_fact_404(self, client):
        r = client.get("/api/facts/fact_doesnotexist")
        assert r.status_code == 404


class TestRelationshipsAPI:
    def test_list_relationships(self, client):
        r = client.get("/api/relationships?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data

    def test_list_rejected_candidates(self, client):
        r = client.get("/api/relationships/rejected-candidates")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_review_nonexistent_relationship_404(self, client):
        r = client.post(
            "/api/relationships/rel_doesnotexist/review",
            json={"review_state": "human_verified"},
        )
        assert r.status_code == 404

    def test_review_invalid_state_400(self, client):
        # We need a real relationship for this — skip if none exist
        r_list = client.get("/api/relationships?limit=1")
        rels = r_list.json().get("items", [])
        if not rels:
            pytest.skip("No relationships to test review endpoint")

        rel_id = rels[0]["relationship_id"]
        r = client.post(
            f"/api/relationships/{rel_id}/review",
            json={"review_state": "invalid_state"},
        )
        assert r.status_code == 400


class TestUIRoutes:
    def test_index_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_document_page_returns_html(self, client):
        r = client.get("/documents/doc_test123")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_fact_page_returns_html(self, client):
        r = client.get("/facts/fact_test123")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
