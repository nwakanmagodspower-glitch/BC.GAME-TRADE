from types import SimpleNamespace

from app.backtest.qualification import qualify_walk_forward


def fold(rate, signals=100, wins=60, losses=40):
    report = SimpleNamespace(
        win_rate_ex_ties=rate,
        signals=signals,
        wins=wins,
        losses=losses,
        ties=0,
    )
    return SimpleNamespace(validation_report=report)


def test_qualification_requires_stable_unseen_evidence():
    report = SimpleNamespace(
        folds=[fold(60.0), fold(58.0), fold(62.0)],
        validation_signals=300,
        validation_wins=180,
        validation_losses=120,
        validation_ties=0,
        validation_win_rate_ex_ties=60.0,
    )
    result = qualify_walk_forward(report)
    assert result.qualified_for_forward_test is True
    assert result.wilson_lower_bound_pct is not None


def test_qualification_rejects_small_or_unstable_sample():
    report = SimpleNamespace(
        folds=[fold(72.0, signals=20, wins=14, losses=6)],
        validation_signals=20,
        validation_wins=14,
        validation_losses=6,
        validation_ties=0,
        validation_win_rate_ex_ties=70.0,
    )
    result = qualify_walk_forward(report)
    assert result.qualified_for_forward_test is False
    assert len(result.reasons) >= 1
