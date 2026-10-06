import math

import pytest
from pydantic import ValidationError


def test_gross_margin_uses_selling_price_and_retains_loss():
    from src.services.scoring import gross_margin

    assert gross_margin(11, 34.99) == pytest.approx(68.5624464133)
    assert gross_margin(20, 10) == -100
    assert gross_margin(0, 10) == 100


@pytest.mark.parametrize("cost,price", [(-1, 10), (1, 0), (1, -1), (math.inf, 10), (1, math.nan)])
def test_margin_rejects_invalid_prices(cost, price):
    from src.services.scoring import gross_margin

    with pytest.raises(ValueError):
        gross_margin(cost, price)


def test_weighted_score_and_breakdown_are_transparent():
    from src.schemas.product import Assessment
    from src.services.scoring import score_breakdown

    assessment = Assessment(demand=8, competition=4, trend=7, marketing=9)
    result = score_breakdown(assessment, 60)
    # 20 demand + 15 margin + 14 trend + 9 inverse competition + 13.5 marketing.
    assert result.total == 71.5
    assert result.components == {
        "Demand": 20.0,
        "Profit margin": 15.0,
        "Trend": 14.0,
        "Competition (inverted)": 9.0,
        "Marketing": 13.5,
    }
    assert result.profit_potential == 6


def test_lower_competition_improves_score_by_fifteen_points():
    from src.schemas.product import Assessment
    from src.services.scoring import score_breakdown

    low = score_breakdown(Assessment(demand=5, competition=0, trend=5, marketing=5), 50)
    high = score_breakdown(Assessment(demand=5, competition=10, trend=5, marketing=5), 50)
    assert low.total - high.total == 15


def test_margin_score_clamps_losses_and_total_reaches_bounds():
    from src.schemas.product import Assessment
    from src.services.scoring import score_breakdown

    assert (
        score_breakdown(Assessment(demand=0, competition=10, trend=0, marketing=0), -100).total == 0
    )
    assert (
        score_breakdown(Assessment(demand=10, competition=0, trend=10, marketing=10), 100).total
        == 100
    )


@pytest.mark.parametrize(
    "score,want",
    [
        (75, "Strong candidate"),
        (74.9, "Worth investigating"),
        (55, "Worth investigating"),
        (54.9, "Weak candidate"),
    ],
)
def test_recommendation_thresholds(score, want):
    from src.services.scoring import recommendation

    assert recommendation(score) == want


@pytest.mark.parametrize("field,value", [("demand", -1), ("trend", 11), ("competition", math.nan)])
def test_assessment_rejects_invalid_scores(field, value):
    from src.schemas.product import Assessment

    with pytest.raises(ValidationError):
        Assessment(**({"demand": 5, "competition": 5, "trend": 5, "marketing": 5} | {field: value}))


def test_product_validates_text_and_price_and_normalizes_identity():
    from src.schemas.product import Product

    a = Product(name="  Pet   Hair Remover ", category="PET", cost=5, selling_price=20)
    b = Product(name="pet hair remover", category=" pet ", cost=8, selling_price=30)
    assert a.id == b.id
    assert a.name == "Pet Hair Remover"
    for changes in ({"name": "  "}, {"cost": -1}, {"selling_price": 0}, {"cost": math.inf}):
        with pytest.raises(ValidationError):
            Product(
                **({"name": "Test", "category": "Pet", "cost": 5, "selling_price": 20} | changes)
            )


@pytest.mark.parametrize("field,value", [("name", None), ("name", 42), ("category", None)])
def test_malformed_text_inputs_produce_controlled_validation_errors(field, value):
    from src.schemas.product import Product

    with pytest.raises(ValidationError):
        Product(
            **({"name": "Test", "category": "Pet", "cost": 5, "selling_price": 20} | {field: value})
        )
