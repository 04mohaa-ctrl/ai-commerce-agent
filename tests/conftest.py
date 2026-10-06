import pytest

from src.schemas.product import Product
from src.services.scoring import build_result


@pytest.fixture
def product():
    return Product(
        name="Pet Hair Remover",
        category="Pet products",
        cost=4,
        selling_price=20,
        description="Reusable roller for furniture",
        tags=["pet accessories"],
    )


@pytest.fixture
def result(product):
    from src.schemas.product import Assessment

    return build_result(product, Assessment(demand=8, competition=4, trend=7, marketing=9))
