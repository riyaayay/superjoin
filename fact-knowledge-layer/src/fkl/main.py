"""FastAPI application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from fkl.api.routers import documents, facts, health, relationships
from fkl.config import get_settings
from fkl.persistence.database import init_db

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE / "web" / "templates"
_STATIC_DIR = _HERE / "web" / "static"


def create_app() -> FastAPI:
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = FastAPI(
        title="Fact Knowledge Layer",
        description="Evidence-first fact extraction and relationship discovery for PDF documents.",
        version="0.1.0",
    )

    # Init DB
    init_db(settings.database_url)

    # Templates — cache_size=0 fixes Jinja2 3.1.x unhashable-dict LRUCache bug with starlette
    import jinja2
    jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html"]),
        cache_size=0,  # disable LRU cache to avoid TypeError: unhashable type: 'dict'
    )
    tmpl = Jinja2Templates(env=jinja_env)

    # Routers
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(facts.router)
    app.include_router(relationships.router)

    # Static files
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # UI routes
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request):
        return tmpl.TemplateResponse(request, "index.html")

    @app.get("/documents/{document_id}", response_class=HTMLResponse, include_in_schema=False)
    async def document_detail(request: Request, document_id: str):
        return tmpl.TemplateResponse(request, "document.html", {"document_id": document_id})

    @app.get("/facts/{fact_id}", response_class=HTMLResponse, include_in_schema=False)
    async def fact_detail(request: Request, fact_id: str):
        return tmpl.TemplateResponse(request, "fact_detail.html", {"fact_id": fact_id})

    return app


app = create_app()
