import uuid
import logging
from typing import Optional

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    models,
)

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

KNOWLEDGE_COLLECTION = "knowledge_base"
INTENT_COLLECTION = "intent_examples"
PRODUCT_COLLECTION = "product_catalog"


class VectorStoreService:
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
        self._embedding_client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            timeout=30,
        )

    async def initialize_collections(self):
        """Create collections if they don't exist."""
        for collection_name in [KNOWLEDGE_COLLECTION, INTENT_COLLECTION, PRODUCT_COLLECTION]:
            collections = await self.client.get_collections()
            existing = [c.name for c in collections.collections]
            if collection_name not in existing:
                await self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=settings.embedding_dimensions,
                        distance=Distance.COSINE,
                    ),
                )
                # Create payload index for tenant isolation
                await self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name="tenant_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                logger.info(f"Created collection: {collection_name}")

    async def get_embedding(self, text: str) -> list[float]:
        """Get embedding vector from OpenAI."""
        response = await self._embedding_client.post(
            "/embeddings",
            json={
                "input": text,
                "model": settings.embedding_model,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embedding vectors for multiple texts."""
        response = await self._embedding_client.post(
            "/embeddings",
            json={
                "input": texts,
                "model": settings.embedding_model,
            },
        )
        response.raise_for_status()
        data = response.json()
        # Sort by index to maintain order
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]

    async def upsert_knowledge_chunks(
        self,
        tenant_id: str,
        chunks: list[dict],
    ) -> list[str]:
        """
        Upsert knowledge base chunks for a tenant.
        Each chunk: {"content": str, "document_id": str, "chunk_index": int, "title": str}
        Returns list of Qdrant point IDs.
        """
        texts = [c["content"] for c in chunks]
        embeddings = await self.get_embeddings_batch(texts)

        points = []
        point_ids = []
        for chunk, embedding in zip(chunks, embeddings):
            point_id = str(uuid.uuid4())
            point_ids.append(point_id)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "tenant_id": tenant_id,
                        "content": chunk["content"],
                        "document_id": chunk["document_id"],
                        "chunk_index": chunk["chunk_index"],
                        "title": chunk.get("title", ""),
                        "type": "knowledge",
                    },
                )
            )

        await self.client.upsert(
            collection_name=KNOWLEDGE_COLLECTION,
            points=points,
        )
        logger.info(f"Upserted {len(points)} knowledge chunks for tenant {tenant_id}")
        return point_ids

    async def upsert_intent_examples(
        self,
        tenant_id: str,
        intent_name: str,
        examples: list[str],
        action_type: str,
        action_config: dict,
    ) -> list[str]:
        """Upsert intent example embeddings for a tenant."""
        embeddings = await self.get_embeddings_batch(examples)

        points = []
        point_ids = []
        for example, embedding in zip(examples, embeddings):
            point_id = str(uuid.uuid4())
            point_ids.append(point_id)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "tenant_id": tenant_id,
                        "intent_name": intent_name,
                        "example_text": example,
                        "action_type": action_type,
                        "action_config": action_config,
                        "type": "intent",
                    },
                )
            )

        await self.client.upsert(
            collection_name=INTENT_COLLECTION,
            points=points,
        )
        logger.info(f"Upserted {len(points)} intent examples for tenant {tenant_id}, intent={intent_name}")
        return point_ids

    async def search_knowledge(
        self,
        tenant_id: str,
        query: str,
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """Search knowledge base for relevant chunks."""
        if top_k is None:
            top_k = settings.rag_top_k

        query_embedding = await self.get_embedding(query)

        results = await self.client.search(
            collection_name=KNOWLEDGE_COLLECTION,
            query_vector=query_embedding,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=tenant_id),
                    )
                ]
            ),
            limit=top_k,
            score_threshold=0.3,
        )

        return [
            {
                "content": hit.payload["content"],
                "title": hit.payload.get("title", ""),
                "score": hit.score,
                "document_id": hit.payload.get("document_id", ""),
            }
            for hit in results
        ]

    async def detect_intent(
        self,
        tenant_id: str,
        message: str,
        threshold: float = 0.5,
    ) -> Optional[dict]:
        """Detect intent from message using vector similarity."""
        query_embedding = await self.get_embedding(message)

        results = await self.client.search(
            collection_name=INTENT_COLLECTION,
            query_vector=query_embedding,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=tenant_id),
                    )
                ]
            ),
            limit=3,
            score_threshold=threshold,
        )

        if not results:
            return None

        # Return best matching intent
        best = results[0]
        return {
            "intent_name": best.payload["intent_name"],
            "confidence": best.score,
            "action_type": best.payload["action_type"],
            "action_config": best.payload.get("action_config", {}),
            "matched_example": best.payload.get("example_text", ""),
        }

    async def delete_tenant_data(self, tenant_id: str):
        """Delete all vectors for a tenant."""
        for collection_name in [KNOWLEDGE_COLLECTION, INTENT_COLLECTION, PRODUCT_COLLECTION]:
            await self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="tenant_id",
                                match=MatchValue(value=tenant_id),
                            )
                        ]
                    )
                ),
            )
        logger.info(f"Deleted all vector data for tenant {tenant_id}")

    async def upsert_product(
        self,
        tenant_id: str,
        product_id: str,
        text: str,
        metadata: dict,
    ) -> str:
        """Embed and store a product for semantic matching."""
        embedding = await self.get_embedding(text)
        point_id = str(uuid.uuid4())
        await self.client.upsert(
            collection_name=PRODUCT_COLLECTION,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "tenant_id": tenant_id,
                        "product_id": product_id,
                        "content": text,
                        "category": metadata.get("category", ""),
                        "price": metadata.get("price"),
                        "name": metadata.get("name", ""),
                        "tags": metadata.get("tags", []),
                        "type": "product",
                    },
                )
            ],
        )
        logger.info(f"Upserted product {product_id} for tenant {tenant_id}")
        return point_id

    async def search_products(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 3,
        category_filter: Optional[str] = None,
    ) -> list[dict]:
        """Search product catalog for relevant products."""
        query_embedding = await self.get_embedding(query)
        must_conditions = [
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))
        ]
        if category_filter:
            must_conditions.append(
                FieldCondition(key="category", match=MatchValue(value=category_filter))
            )

        results = await self.client.search(
            collection_name=PRODUCT_COLLECTION,
            query_vector=query_embedding,
            query_filter=Filter(must=must_conditions),
            limit=top_k,
            score_threshold=settings.sales_product_match_threshold,
        )

        return [
            {
                "product_id": hit.payload["product_id"],
                "name": hit.payload.get("name", ""),
                "content": hit.payload["content"],
                "category": hit.payload.get("category", ""),
                "price": hit.payload.get("price"),
                "tags": hit.payload.get("tags", []),
                "score": hit.score,
            }
            for hit in results
        ]

    async def delete_product_vectors(self, tenant_id: str, point_id: str):
        """Delete a specific product vector."""
        await self.client.delete(
            collection_name=PRODUCT_COLLECTION,
            points_selector=models.PointIdsList(points=[point_id]),
        )
        logger.info(f"Deleted product vector {point_id} for tenant {tenant_id}")

    async def close(self):
        await self._embedding_client.aclose()
        await self.client.close()
