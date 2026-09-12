"""Vercel serverless function entrypoint for FastAPI."""

import os
import shutil
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
FKL_SRC = ROOT_DIR / "fact-knowledge-layer" / "src"

if str(FKL_SRC) not in sys.path:
    sys.path.insert(0, str(FKL_SRC))

# Vercel Serverless environment handling
# On Vercel, the filesystem is read-only except /tmp
if "VERCEL" in os.environ or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    tmp_dir = Path("/tmp")
    data_dir = tmp_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    render_dir = data_dir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)

    db_file = data_dir / "fkl.sqlite3"

    # Copy starter snapshot or pre-seeded database to /tmp if it doesn't exist
    starter_dbs = [
        ROOT_DIR / "fact-knowledge-layer" / "data" / "fkl_starter_snapshot.sqlite3",
        ROOT_DIR / "fact-knowledge-layer" / "data" / "fkl.sqlite3",
    ]
    if not db_file.exists():
        for sdb in starter_dbs:
            if sdb.exists():
                shutil.copyfile(sdb, db_file)
                break

    os.environ.setdefault("DATABASE_URL", f"sqlite:///{db_file}")
    os.environ.setdefault("UPLOAD_DIR", str(upload_dir))
    os.environ.setdefault("RENDER_DIR", str(render_dir))

from fkl.main import app
