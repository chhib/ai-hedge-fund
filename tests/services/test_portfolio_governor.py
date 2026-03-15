from pathlib import Path

from src.analytics.scorecard import AnalystScore, RegimeScorecardResult
from src.services.portfolio_governor import GovernorSnapshot, GovernorStore, PortfolioGovernor


def _score(
    analyst_name: str,
    *,
    credibility: float,
    hit_rate: float,
    avg_alpha: float,
    conviction_rate: float,
) -> AnalystScore:
    return AnalystScore(
        analyst_name=analyst_name,
        display_name=analyst_name,
        total_signals=100,
        evaluated=80,
        neutral_skipped=20,
        hit_rate=hit_rate,
        credibility=credibility,
        avg_alpha=avg_alpha,
        conviction_rate=conviction_rate,
    )


def _regime_scorecard() -> RegimeScorecardResult:
    tech = _score(
        "technical_analyst",
        credibility=1.35,
        hit_rate=0.61,
        avg_alpha=0.03,
        conviction_rate=0.55,
    )
    fundamentals = _score(
        "fundamentals_analyst",
        credibility=0.82,
        hit_rate=0.49,
        avg_alpha=-0.01,
        conviction_rate=0.15,
    )
    return RegimeScorecardResult(
        analyst_scores=[tech, fundamentals],
        regime_scores={"high_vol": [tech, fundamentals]},
        benchmark_ticker="OMXS30",
        regime_by_date={"2026-03-14": "high_vol"},
        date_range="2026-01-01 to 2026-03-14",
        evaluable_dates=10,
        horizon=7,
        total_outcomes=160,
    )


def test_governor_throttles_and_downweights_in_high_vol() -> None:
    governor = PortfolioGovernor()

    decision = governor.evaluate(
        selected_analysts=["technical_analyst", "fundamentals_analyst"],
        aggregated_scores={"AAA": 0.70, "BBB": 0.05, "CCC": 0.02},
        max_position=0.25,
        scorecard_result=_regime_scorecard(),
        benchmark_drawdown_pct=-6.0,
        persist=False,
    )

    assert decision.risk_state == "warning"
    assert decision.deployment_ratio <= 0.50
    assert decision.min_cash_buffer >= 0.25
    assert decision.analyst_weights["technical_analyst"] > decision.analyst_weights["fundamentals_analyst"]
    assert any("High-volatility regime" in reason for reason in decision.reasons)


def test_governor_halts_on_large_drawdown() -> None:
    governor = PortfolioGovernor()

    decision = governor.evaluate(
        selected_analysts=["technical_analyst"],
        aggregated_scores={"AAA": 0.80},
        max_position=0.25,
        scorecard_result=_regime_scorecard(),
        benchmark_drawdown_pct=-14.0,
        persist=False,
    )

    assert decision.trading_enabled is False
    assert decision.risk_state == "halted"
    assert decision.deployment_ratio == 0.0
    assert decision.min_cash_buffer == 1.0


def test_governor_store_round_trip(tmp_path: Path) -> None:
    store = GovernorStore(tmp_path / "governor.db")
    governor = PortfolioGovernor(store=store)
    decision = governor.evaluate(
        selected_analysts=["technical_analyst"],
        aggregated_scores={"AAA": 0.60},
        max_position=0.25,
        scorecard_result=_regime_scorecard(),
        benchmark_drawdown_pct=-4.0,
        persist=False,
    )

    snapshot = GovernorSnapshot.from_decision(decision, created_at="2026-03-15T12:00:00")
    store.save_snapshot(snapshot)
    loaded = store.latest_snapshot()

    assert loaded is not None
    assert loaded.created_at == "2026-03-15T12:00:00"
    assert loaded.analyst_weights["technical_analyst"] == snapshot.analyst_weights["technical_analyst"]
