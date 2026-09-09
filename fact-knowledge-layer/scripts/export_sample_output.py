"""Export sample output — saves redacted JSON for graders."""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx

BASE_URL = "http://localhost:8000"
OUT_DIR = Path("sample-output")
OUT_DIR.mkdir(exist_ok=True)


def main():
    with httpx.Client() as client:
        # Facts sample
        r = client.get(f"{BASE_URL}/api/facts?limit=20", timeout=30)
        r.raise_for_status()
        facts_data = r.json()
        # Redact document paths
        for f in facts_data.get("items", []):
            if "evidence" in f:
                f["evidence"].pop("text", None)  # keep context, drop full text
        (OUT_DIR / "sample_facts.json").write_text(json.dumps(facts_data, indent=2))
        print(f"Saved {len(facts_data['items'])} facts to sample-output/sample_facts.json")

        # Relationships sample
        r = client.get(f"{BASE_URL}/api/relationships?limit=20", timeout=30)
        r.raise_for_status()
        rels_data = r.json()
        (OUT_DIR / "sample_relationships.json").write_text(json.dumps(rels_data, indent=2))
        print(f"Saved {len(rels_data['items'])} relationships to sample-output/sample_relationships.json")

        # Rejected candidates sample
        r = client.get(f"{BASE_URL}/api/relationships/rejected-candidates?limit=10", timeout=30)
        r.raise_for_status()
        rejected_data = r.json()
        (OUT_DIR / "sample_rejected.json").write_text(json.dumps(rejected_data, indent=2))
        print(f"Saved {len(rejected_data)} rejected candidates to sample-output/sample_rejected.json")

    print("\nDone. sample-output/ is safe to commit.")


if __name__ == "__main__":
    main()
