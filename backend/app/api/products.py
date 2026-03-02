import logging
import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant
from app.models.product import Product, ProductStatus
from app.api.auth import get_current_tenant
from app.services.vector_store import VectorStoreService
from app.services.product import ProductService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["products"])


class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    currency: str = "USD"
    image_url: Optional[str] = None
    action_url: Optional[str] = None
    tags: list[str] = []
    metadata_json: dict = {}
    sort_order: int = 0


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    image_url: Optional[str] = None
    action_url: Optional[str] = None
    status: Optional[ProductStatus] = None
    tags: Optional[list[str]] = None
    metadata_json: Optional[dict] = None
    sort_order: Optional[int] = None


class ProductResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    price: Optional[float]
    currency: str
    image_url: Optional[str]
    action_url: Optional[str]
    status: str
    tags: list[str]
    metadata_json: dict
    sort_order: int
    created_at: str

    class Config:
        from_attributes = True


class ProductSearchRequest(BaseModel):
    query: str
    top_k: int = 3
    category: Optional[str] = None


class ProductImportItem(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    currency: str = "USD"
    image_url: Optional[str] = None
    action_url: Optional[str] = None
    tags: list[str] = []
    metadata_json: dict = {}


def _product_response(p: Product) -> ProductResponse:
    return ProductResponse(
        id=str(p.id),
        name=p.name,
        description=p.description,
        category=p.category,
        price=p.price,
        currency=p.currency,
        image_url=p.image_url,
        action_url=p.action_url,
        status=p.status.value,
        tags=p.tags or [],
        metadata_json=p.metadata_json or {},
        sort_order=p.sort_order,
        created_at=p.created_at.isoformat(),
    )


@router.post("", response_model=ProductResponse)
async def create_product(
    data: ProductCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new product and embed in vector store."""
    vector_store = VectorStoreService()
    try:
        product = await ProductService.create_product(
            db, str(tenant.id), data.model_dump(), vector_store
        )
        return _product_response(product)
    except Exception as e:
        logger.exception("Product creation failed")
        raise HTTPException(status_code=500, detail=f"Product creation error: {str(e)}")
    finally:
        await vector_store.close()


@router.get("", response_model=list[ProductResponse])
async def list_products(
    category: Optional[str] = None,
    status: Optional[ProductStatus] = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all products for the current tenant."""
    query = select(Product).where(Product.tenant_id == tenant.id)
    if category:
        query = query.where(Product.category == category)
    if status:
        query = query.where(Product.status == status)
    query = query.order_by(Product.sort_order, Product.created_at)

    result = await db.execute(query)
    products = result.scalars().all()
    return [_product_response(p) for p in products]


def _validate_uuid(value: str) -> str:
    try:
        _uuid.UUID(value)
        return value
    except ValueError:
        raise HTTPException(status_code=404, detail="Product not found")


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get a single product."""
    _validate_uuid(product_id)
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product_response(product)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    data: ProductUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update a product."""
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        return _product_response(product)

    vector_store = VectorStoreService()
    try:
        product = await ProductService.update_product(db, product, update_data, vector_store)
        return _product_response(product)
    except Exception as e:
        logger.exception("Product update failed")
        raise HTTPException(status_code=500, detail=f"Product update error: {str(e)}")
    finally:
        await vector_store.close()


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a product."""
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    vector_store = VectorStoreService()
    try:
        await ProductService.delete_product(db, product, vector_store)
    except Exception as e:
        logger.exception("Product deletion failed")
        raise HTTPException(status_code=500, detail=f"Product deletion error: {str(e)}")
    finally:
        await vector_store.close()

    return {"status": "deleted"}


@router.post("/search")
async def search_products(
    data: ProductSearchRequest,
    tenant: Tenant = Depends(get_current_tenant),
):
    """Semantic search products."""
    vector_store = VectorStoreService()
    try:
        results = await vector_store.search_products(
            tenant_id=str(tenant.id),
            query=data.query,
            top_k=data.top_k,
            category_filter=data.category,
        )
        return {"results": results}
    except Exception as e:
        logger.exception("Product search failed")
        raise HTTPException(status_code=500, detail=f"Product search error: {str(e)}")
    finally:
        await vector_store.close()


@router.post("/import")
async def import_products(
    items: list[ProductImportItem],
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Bulk import products."""
    vector_store = VectorStoreService()
    created = []
    try:
        for item in items:
            product = await ProductService.create_product(
                db, str(tenant.id), item.model_dump(), vector_store
            )
            created.append(_product_response(product))
        return {"imported": len(created), "products": created}
    except Exception as e:
        logger.exception("Product import failed")
        raise HTTPException(status_code=500, detail=f"Import error: {str(e)}")
    finally:
        await vector_store.close()
