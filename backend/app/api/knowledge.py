import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.api.auth import get_current_tenant
from app.services.vector_store import VectorStoreService
from app.services.rag import chunk_text
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
settings = get_settings()


class DocumentCreate(BaseModel):
    title: str
    content: str


class DocumentResponse(BaseModel):
    id: str
    title: str
    source_filename: str | None
    chunk_count: int
    created_at: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchResult(BaseModel):
    content: str
    title: str
    score: float


@router.post("", response_model=DocumentResponse)
async def upload_document(
    data: DocumentCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Upload a knowledge base document. Content is chunked and embedded."""
    limits = tenant.get_plan_limits()
    max_docs = limits["max_documents"]

    if max_docs > 0:
        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant.id)
        )
        current_count = len(result.scalars().all())
        if current_count >= max_docs:
            raise HTTPException(
                status_code=403,
                detail=f"Plan limit reached: max {max_docs} documents allowed",
            )

    # Chunk the content
    chunks = chunk_text(
        data.content,
        chunk_size=settings.rag_chunk_size,
        overlap=settings.rag_chunk_overlap,
    )

    if not chunks:
        raise HTTPException(status_code=422, detail="Document content is empty")

    # Save document
    doc = KnowledgeDocument(
        tenant_id=tenant.id,
        title=data.title,
        content=data.content,
        chunk_count=len(chunks),
    )
    db.add(doc)
    await db.flush()

    # Embed and store in vector DB
    vector_store = VectorStoreService()
    try:
        chunk_dicts = [
            {
                "content": chunk,
                "document_id": str(doc.id),
                "chunk_index": i,
                "title": data.title,
            }
            for i, chunk in enumerate(chunks)
        ]

        point_ids = await vector_store.upsert_knowledge_chunks(
            tenant_id=str(tenant.id),
            chunks=chunk_dicts,
        )

        # Save chunk references
        for i, (chunk, point_id) in enumerate(zip(chunks, point_ids)):
            db_chunk = KnowledgeChunk(
                document_id=doc.id,
                chunk_index=i,
                content=chunk,
                qdrant_point_id=point_id,
            )
            db.add(db_chunk)

        await db.flush()
    finally:
        await vector_store.close()

    return DocumentResponse(
        id=str(doc.id),
        title=doc.title,
        source_filename=doc.source_filename,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at.isoformat(),
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all knowledge base documents."""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.tenant_id == tenant.id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    docs = result.scalars().all()
    return [
        DocumentResponse(
            id=str(d.id),
            title=d.title,
            source_filename=d.source_filename,
            chunk_count=d.chunk_count,
            created_at=d.created_at.isoformat(),
        )
        for d in docs
    ]


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a knowledge base document and its vectors."""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.tenant_id == tenant.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    await db.delete(doc)
    await db.flush()

    return {"status": "deleted"}


@router.post("/search", response_model=list[SearchResult])
async def search_knowledge(
    data: SearchRequest,
    tenant: Tenant = Depends(get_current_tenant),
):
    """Search the knowledge base using semantic search."""
    vector_store = VectorStoreService()
    try:
        results = await vector_store.search_knowledge(
            tenant_id=str(tenant.id),
            query=data.query,
            top_k=data.top_k,
        )
    finally:
        await vector_store.close()

    return [
        SearchResult(
            content=r["content"],
            title=r["title"],
            score=r["score"],
        )
        for r in results
    ]
