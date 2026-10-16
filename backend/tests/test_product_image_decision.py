import pytest

from app.clients.product_visual_verifier import ProductVisualMatch
from app.services.product_image_decision import ProductImageDecisionEngine


def decision_engine() -> ProductImageDecisionEngine:
    return ProductImageDecisionEngine(
        vector_weight=0.55,
        visual_weight=0.45,
        verify_min_score=0.65,
        high_confidence=0.82,
        medium_confidence=0.65,
    )


def test_decision_engine_can_rerank_candidates_with_visual_scores():
    decision = decision_engine().decide(
        [
            {"product_code": "SKU01", "similarity": 0.86},
            {"product_code": "SKU02", "similarity": 0.82},
        ],
        [
            ProductVisualMatch("SKU01", 0.55, "Khác chi tiết"),
            ProductVisualMatch("SKU02", 0.98, "Khớp kiểu dáng"),
        ],
    )

    assert decision.verification_applied is True
    assert decision.ranked_matches[0]["product_code"] == "SKU02"
    assert decision.ranked_matches[0]["similarity"] == pytest.approx(0.892)
    assert decision.confidence == "high"


def test_decision_engine_falls_back_when_no_verified_score_reaches_minimum():
    original = [
        {"product_code": "SKU01", "similarity": 0.60},
        {"product_code": "SKU02", "similarity": 0.55},
    ]
    decision = decision_engine().decide(
        original,
        [
            ProductVisualMatch("SKU01", 0.20, "Không giống"),
            ProductVisualMatch("SKU02", 0.25, "Không giống"),
        ],
    )

    assert decision.ranked_matches == original
    assert decision.confidence == "low"
    assert decision.verification_applied is True


def test_low_visual_scores_cannot_override_the_vector_winner():
    original = [
        {"product_code": "G5863", "similarity": 0.857},
        {"product_code": "G81U4", "similarity": 0.822},
    ]

    decision = decision_engine().decide(
        original,
        [
            ProductVisualMatch("G5863", 0.40, "Không đủ giống"),
            ProductVisualMatch("G81U4", 0.45, "Không đủ giống"),
        ],
    )

    assert decision.ranked_matches == original
    assert decision.ranked_matches[0]["product_code"] == "G5863"
    assert decision.confidence == "low"
    assert decision.verification_applied is True

