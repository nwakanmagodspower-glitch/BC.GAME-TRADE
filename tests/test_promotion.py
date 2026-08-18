from app.backtest.promotion import evaluate_promotion
from app.backtest.qualification import QualificationResult


class DummyReport:
    pass


def test_same_version_cannot_be_promoted(monkeypatch):
    monkeypatch.setattr(
        'app.backtest.promotion.qualify_walk_forward',
        lambda report: QualificationResult(
            qualified_for_forward_test=True,
            reasons=['ok'],
            validation_signals=500,
            validation_win_rate=60.0,
            wilson_lower_bound_pct=56.0,
            fold_win_rate_stddev=3.0,
            positive_folds=4,
            total_folds=5,
        ),
    )
    decision = evaluate_promotion(
        DummyReport(),
        current_version='BTC_UPDOWN_V1.0',
        candidate_version='BTC_UPDOWN_V1.0',
    )
    assert decision.eligible is False
    assert any('new strategy version' in reason for reason in decision.reasons)


def test_candidate_outside_scope_cannot_be_promoted(monkeypatch):
    monkeypatch.setattr(
        'app.backtest.promotion.qualify_walk_forward',
        lambda report: QualificationResult(
            qualified_for_forward_test=True,
            reasons=['ok'],
            validation_signals=500,
            validation_win_rate=60.0,
            wilson_lower_bound_pct=56.0,
            fold_win_rate_stddev=3.0,
            positive_folds=4,
            total_folds=5,
        ),
    )
    decision = evaluate_promotion(
        DummyReport(),
        current_version='BTC_UPDOWN_V1.0',
        candidate_version='ETH_UPDOWN_V2.0',
    )
    assert decision.eligible is False
    assert any('BTC Up/Down scope' in reason for reason in decision.reasons)
