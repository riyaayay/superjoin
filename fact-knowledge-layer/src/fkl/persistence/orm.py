"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String)

    runs: Mapped[list[IngestionRunORM]] = relationship("IngestionRunORM", back_populates="document")
    blocks: Mapped[list[SourceBlockORM]] = relationship("SourceBlockORM", back_populates="document")
    facts: Mapped[list[FactORM]] = relationship("FactORM", back_populates="document")


class IngestionRunORM(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String, nullable=False)
    parser_version: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String)
    facts_created: Mapped[int] = mapped_column(Integer, default=0)
    facts_rejected: Mapped[int] = mapped_column(Integer, default=0)
    relationships_created: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[DocumentORM] = relationship("DocumentORM", back_populates="runs")


class SourceBlockORM(Base):
    __tablename__ = "source_blocks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    pdf_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_label: Mapped[str | None] = mapped_column(String)
    block_kind: Mapped[str] = mapped_column(String, nullable=False)
    bbox_json: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    table_context_json: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    document: Mapped[DocumentORM] = relationship("DocumentORM", back_populates="blocks")

    __table_args__ = (
        Index("ix_source_blocks_doc_page", "document_id", "pdf_page_index"),
    )


class FactORM(Base):
    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    evidence_block_id: Mapped[str] = mapped_column(ForeignKey("source_blocks.id"), nullable=False)
    entity_raw: Mapped[str] = mapped_column(Text, nullable=False)
    metric_raw: Mapped[str] = mapped_column(Text, nullable=False)
    metric_key: Mapped[str | None] = mapped_column(Text)
    value_raw: Mapped[str] = mapped_column(Text, nullable=False)
    numeric_value: Mapped[float | None] = mapped_column(Float)
    value_kind: Mapped[str] = mapped_column(String, nullable=False)
    unit_raw: Mapped[str | None] = mapped_column(Text)
    unit_dimension: Mapped[str] = mapped_column(String, default="unknown")
    scale_raw: Mapped[str | None] = mapped_column(String)
    normalised_value: Mapped[float | None] = mapped_column(Float)
    normalised_unit: Mapped[str | None] = mapped_column(String)
    period_raw: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[str | None] = mapped_column(String)
    period_end: Mapped[str | None] = mapped_column(String)
    scope_json: Mapped[str] = mapped_column(Text, default="{}")
    qualifiers_json: Mapped[str] = mapped_column(Text, default="{}")
    extraction_method: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    review_state: Mapped[str] = mapped_column(String, nullable=False, default="accepted")
    normalisation_provenance_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    document: Mapped[DocumentORM] = relationship("DocumentORM", back_populates="facts")

    __table_args__ = (
        Index("ix_facts_doc", "document_id"),
        Index("ix_facts_metric_entity", "metric_key", "entity_raw"),
    )


class RelationshipORM(Base):
    __tablename__ = "relationships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    left_fact_id: Mapped[str] = mapped_column(ForeignKey("facts.id"), nullable=False)
    right_fact_id: Mapped[str] = mapped_column(ForeignKey("facts.id"), nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    comparison_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    review_state: Mapped[str] = mapped_column(String, nullable=False, default="automatic")
    created_by_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("left_fact_id", "right_fact_id"),)


class CandidateAuditORM(Base):
    """Rejected candidates — persisted for transparency and demo case #4."""

    __tablename__ = "candidate_audit"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    evidence_block_id: Mapped[str | None] = mapped_column(ForeignKey("source_blocks.id"))
    entity_raw: Mapped[str] = mapped_column(Text)
    metric_raw: Mapped[str] = mapped_column(Text)
    value_raw: Mapped[str] = mapped_column(Text)
    rejection_reason: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
