from types import SimpleNamespace

from app.backtest.feature_report import build_feature_research_report


def report(win_rate, coverage, signals):
    return SimpleNamespace(win_rate_ex_ties=win_rate, coverage_pct=coverage, signals=signals)


def test_classifies_helpful_harmful_and_inconclusive():
    baseline = report(60.0, 20.0, 300)
    ablations = [
        SimpleNamespace(name='trend', win_rate_delta_pct=-2.5, coverage_delta_pct=-1.0, report=report(57.5, 19.0, 250)),
        SimpleNamespace(name='volume', win_rate_delta_pct=2.0, coverage_delta_pct=0.5, report=report(62.0, 20.5, 240)),
        SimpleNamespace(name='structure', win_rate_delta_pct=0.3, coverage_delta_pct=0.1, report=report(60.3, 20.1, 220)),
    ]

    result = build_feature_research_report(baseline, ablations, minimum_signals=100, meaningful_delta_pct=1.0)
    by_family = {item.family: item for item in result.assessments}

    assert by_family['trend'].classification == 'HELPFUL'
    assert by_family['volume'].classification == 'HARMFUL_CANDIDATE'
    assert by_family['structure'].classification == 'INCONCLUSIVE'


def test_small_sample_remains_inconclusive_even_with_large_delta():
    baseline = report(60.0, 20.0, 300)
    ablations = [
        SimpleNamespace(name='momentum', win_rate_delta_pct=8.0, coverage_delta_pct=1.0, report=report(68.0, 21.0, 20)),
    ]

    result = build_feature_research_report(baseline, ablations, minimum_signals=100)
    assert result.assessments[0].classification == 'INCONCLUSIVE'
