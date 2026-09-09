import json
import sqlite3
import uuid
from datetime import datetime, timezone

conn = sqlite3.connect("data/fkl.sqlite3")
cur = conn.cursor()

# Check chart blocks
chart_blocks = cur.execute("SELECT id, document_id, text FROM source_blocks WHERE block_kind IN ('chart', 'image')").fetchall()
print(f"Found {len(chart_blocks)} chart/image blocks")
for b in chart_blocks[:5]:
    print("  Chart block:", b[0], b[1], repr(b[2][:60]))

# Check table cells with missing row_header but numeric cell_value
import re
_NUMERIC_RE = re.compile(r"^[\(\-]?[\d,]+\.?\d*\%?\)?$")

missing_header_cells = []
for row in cur.execute("SELECT id, document_id, table_context_json FROM source_blocks WHERE block_kind = 'table_cell'").fetchall():
    b_id, doc_id, ctx_json = row
    if not ctx_json:
        continue
    try:
        ctx = json.loads(ctx_json)
        cell_val = (ctx.get("cell_value") or "").strip()
        row_hdr = (ctx.get("row_header") or "").strip()
        if cell_val and not row_hdr:
            s = cell_val.replace(" ", "")
            if _NUMERIC_RE.match(s):
                missing_header_cells.append((b_id, doc_id, ctx.get("table_title") or "Table", cell_val))
    except Exception:
        pass

print(f"Found {len(missing_header_cells)} numeric table cells with missing row headers")
for c in missing_header_cells[:5]:
    print("  Table missing header:", c)
