"""Seed demo script — uploads the three starter PDFs and waits for completion.

Usage:
    python scripts/seed_demo.py [--base-url http://localhost:8000] [--pdf-dir ../starter-datasets/india-macroeconomy]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx


def upload_pdf(client: httpx.Client, base_url: str, pdf_path: Path) -> str:
    print(f"\n→ Uploading: {pdf_path.name}")
    with open(pdf_path, "rb") as f:
        r = client.post(f"{base_url}/api/documents", files={"file": (pdf_path.name, f, "application/pdf")}, timeout=60)
    r.raise_for_status()
    data = r.json()
    doc_id = data["document_id"]
    deduped = data.get("deduplicated", False)
    print(f"  document_id: {doc_id} {'(deduplicated)' if deduped else '(new)'}")
    return doc_id


def wait_for_completion(client: httpx.Client, base_url: str, doc_id: str, timeout: int = 300) -> dict:
    print(f"  Polling {doc_id}…", end="", flush=True)
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        r = client.get(f"{base_url}/api/documents/{doc_id}", timeout=30)
        r.raise_for_status()
        doc = r.json()
        status = doc["status"]
        if status == "complete":
            s = doc.get("stats", {})
            print(f"\n  ✓ complete: {s.get('facts_accepted', '?')} facts, {s.get('relationships', '?')} relationships")
            return doc
        elif status == "failed":
            print(f"\n  ✗ failed: {doc.get('error_message', 'unknown error')}")
            return doc
        else:
            print(".", end="", flush=True)
            time.sleep(2)
    print(f"\n  ⚠ timeout after {timeout}s")
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--pdf-dir", default="../starter-datasets/india-macroeconomy")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.exists():
        print(f"PDF directory not found: {pdf_dir}")
        return

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {pdf_dir}")
        return

    print(f"Found {len(pdfs)} PDFs in {pdf_dir}")
    print(f"API base URL: {args.base_url}\n")

    with httpx.Client() as client:
        # Health check
        try:
            r = client.get(f"{args.base_url}/health", timeout=10)
            r.raise_for_status()
            print("✓ API is healthy")
        except Exception as e:
            print(f"✗ API health check failed: {e}")
            print("  Make sure the server is running: uvicorn fkl.main:app --reload --port 8000")
            return

        doc_ids = []
        for pdf in pdfs:
            doc_id = upload_pdf(client, args.base_url, pdf)
            doc_ids.append(doc_id)

        print("\n\nWaiting for all documents to complete ingestion…")
        results = []
        for doc_id in doc_ids:
            result = wait_for_completion(client, args.base_url, doc_id)
            results.append(result)

        print("\n\n=== Ingestion Summary ===")
        for i, (doc_id, result) in enumerate(zip(doc_ids, results), 1):
            s = result.get("stats", {})
            print(f"{i}. {doc_id}: status={result.get('status', '?')}, "
                  f"facts={s.get('facts_accepted', '?')}, rel={s.get('relationships', '?')}")

        # List relationships
        r = client.get(f"{args.base_url}/api/relationships?limit=10", timeout=30)
        r.raise_for_status()
        rels = r.json()
        print(f"\nTop relationships found: {rels['total']} total")
        for rel in rels['items'][:5]:
            print(f"  [{rel['verdict'].upper()}] {rel['left_fact'].get('metric_raw','?')} "
                  f"| reason: {rel['reason_code']} | conf: {rel['confidence']:.2f}")


if __name__ == "__main__":
    main()
