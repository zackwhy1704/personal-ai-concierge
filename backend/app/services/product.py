import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


class ProductService:
    """Manages product catalog operations."""

    @staticmethod
    def build_embedding_text(name: str, description: str, category: str, tags: list) -> str:
        """Combine product fields into a single text for embedding."""
        parts = [name]
        if description:
            parts.append(description)
        if category:
            parts.append(f"Category: {category}")
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")
        return ". ".join(parts)

    @staticmethod
    async def create_product(
        db: AsyncSession,
        tenant_id: str,
        data: dict,
        vector_store: VectorStoreService,
    ) -> Product:
        """Create a product and embed in Qdrant."""
        product = Product(
            tenant_id=tenant_id,
            name=data["name"],
            description=data.get("description"),
            category=data.get("category"),
            price=data.get("price"),
            currency=data.get("currency", "USD"),
            image_url=data.get("image_url"),
            action_url=data.get("action_url"),
            tags=data.get("tags", []),
            metadata_json=data.get("metadata_json", {}),
            sort_order=data.get("sort_order", 0),
        )
        db.add(product)
        await db.flush()

        embedding_text = ProductService.build_embedding_text(
            product.name,
            product.description or "",
            product.category or "",
            product.tags or [],
        )
        point_id = await vector_store.upsert_product(
            tenant_id=tenant_id,
            product_id=str(product.id),
            text=embedding_text,
            metadata={
                "name": product.name,
                "category": product.category or "",
                "price": product.price,
                "tags": product.tags or [],
            },
        )
        product.qdrant_point_id = point_id
        await db.flush()

        return product

    @staticmethod
    async def update_product(
        db: AsyncSession,
        product: Product,
        data: dict,
        vector_store: VectorStoreService,
    ) -> Product:
        """Update product fields and re-embed if description/name changed."""
        needs_reembed = False
        for field in ["name", "description", "category", "tags"]:
            if field in data and data[field] != getattr(product, field):
                needs_reembed = True

        for field, value in data.items():
            if hasattr(product, field) and field not in ("id", "tenant_id", "created_at"):
                setattr(product, field, value)

        if needs_reembed:
            if product.qdrant_point_id:
                await vector_store.delete_product_vectors(
                    str(product.tenant_id), product.qdrant_point_id
                )
            embedding_text = ProductService.build_embedding_text(
                product.name,
                product.description or "",
                product.category or "",
                product.tags or [],
            )
            point_id = await vector_store.upsert_product(
                tenant_id=str(product.tenant_id),
                product_id=str(product.id),
                text=embedding_text,
                metadata={
                    "name": product.name,
                    "category": product.category or "",
                    "price": product.price,
                    "tags": product.tags or [],
                },
            )
            product.qdrant_point_id = point_id

        await db.flush()
        return product

    @staticmethod
    async def delete_product(
        db: AsyncSession,
        product: Product,
        vector_store: VectorStoreService,
    ):
        """Delete product from DB and Qdrant."""
        if product.qdrant_point_id:
            await vector_store.delete_product_vectors(
                str(product.tenant_id), product.qdrant_point_id
            )
        await db.delete(product)
        await db.flush()
