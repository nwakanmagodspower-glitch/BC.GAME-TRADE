from app.backtest.reporting import FeatureAssessment
from app.backtest.stability import FeatureStability


def classify(items):
    helpful = sum(item.classification == 'HELPFUL' for item in items)
    harmful = sum(item.classification == 'HARMFUL_CANDIDATE' for item in items)
    if len(items) >= 3 and helpful / len(items) >= 0.67 and harmful == 0:
        return 'STABLY_HELPFUL'
    if len(items) >= 3 and harmful / len(items) >= 0.67 and helpful == 0:
        return 'STABLY_HARMFUL_CANDIDATE'
    return 'INCONCLUSIVE'


def assessment(label):
    return FeatureAssessment(
        family='trend',
        classification=label,
        win_rate_delta_pct=-2.0 if label == 'HELPFUL' else 2.0,
        coverage_delta_pct=0.0,
        ablated_signals=200,
        reason='test',
    )


def test_three_consistent_helpful_windows_are_stable():
    assert classify([assessment('HELPFUL')] * 3) == 'STABLY_HELPFUL'


def test_mixed_windows_remain_inconclusive():
    assert classify([
        assessment('HELPFUL'),
        assessment('HARMFUL_CANDIDATE'),
        assessment('INCONCLUSIVE'),
    ]) == 'INCONCLUSIVE'
