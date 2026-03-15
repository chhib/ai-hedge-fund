"""Preservation-first portfolio governor for rebalance and backtest flows."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from src.analytics.scorecard import (
    RegimeLabel,
    RegimeScorecardResult,
    build_price_index,
    build_regime_map,
    build_regime_scorecard,
    resolve_benchmark_ticker,
)

_DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "governor_history.db"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(slots=True)
class AnalystRegimeScore:
    analyst_name: str
    display_name: str
    credibility: float
    hit_rate: float
    avg_alpha: float
    conviction_rate: float
    weight: float
    regime: RegimeLabel


@dataclass(slots=True)
class GovernorDecision:
    profile: str
    benchmark_ticker: str
    regime: RegimeLabel
    risk_state: str
    trading_enabled: bool
    deployment_ratio: float
    analyst_weights: dict[str, float]
    ticker_penalties: dict[str, float]
    max_position_override: float | None
    min_cash_buffer: float
    reasons: list[str]
    average_credibility: float
    average_conviction: float
    bullish_breadth: float
    benchmark_drawdown_pct: float
    analyst_scores: list[AnalystRegimeScore] = field(default_factory=list)


@dataclass(slots=True)
class GovernorSnapshot:
    created_at: str
    profile: str
    benchmark_ticker: str
    regime: RegimeLabel
    risk_state: str
    trading_enabled: bool
    deployment_ratio: float
    min_cash_buffer: float
    max_position_override: float | None
    average_credibility: float
    average_conviction: float
    bullish_breadth: float
    benchmark_drawdown_pct: float
    analyst_weights: dict[str, float]
    ticker_penalties: dict[str, float]
    reasons: list[str]

    @classmethod
    def from_decision(cls, decision: GovernorDecision, *, created_at: Optional[str] = None) -> "GovernorSnapshot":
        return cls(
            created_at=created_at or datetime.utcnow().isoformat(),
            profile=decision.profile,
            benchmark_ticker=decision.benchmark_ticker,
            regime=decision.regime,
            risk_state=decision.risk_state,
            trading_enabled=decision.trading_enabled,
            deployment_ratio=decision.deployment_ratio,
            min_cash_buffer=decision.min_cash_buffer,
            max_position_override=decision.max_position_override,
            average_credibility=decision.average_credibility,
            average_conviction=decision.average_conviction,
            bullish_breadth=decision.bullish_breadth,
            benchmark_drawdown_pct=decision.benchmark_drawdown_pct,
            analyst_weights=dict(decision.analyst_weights),
            ticker_penalties=dict(decision.ticker_penalties),
            reasons=list(decision.reasons),
        )


class GovernorStore:
    """SQLite-backed persistence for governor snapshots."""

    def __init__(self, db_path: Path = _DEFAULT_STORE_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS governor_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    benchmark_ticker TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    risk_state TEXT NOT NULL,
                    trading_enabled INTEGER NOT NULL,
                    deployment_ratio REAL NOT NULL,
                    min_cash_buffer REAL NOT NULL,
                    max_position_override REAL,
                    average_credibility REAL NOT NULL,
                    average_conviction REAL NOT NULL,
                    bullish_breadth REAL NOT NULL,
                    benchmark_drawdown_pct REAL NOT NULL,
                    analyst_weights_json TEXT NOT NULL,
                    ticker_penalties_json TEXT NOT NULL,
                    reasons_json TEXT NOT NULL
                )
                """
            )

    def save_snapshot(self, snapshot: GovernorSnapshot) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO governor_snapshots (
                    created_at,
                    profile,
                    benchmark_ticker,
                    regime,
                    risk_state,
                    trading_enabled,
                    deployment_ratio,
                    min_cash_buffer,
                    max_position_override,
                    average_credibility,
                    average_conviction,
                    bullish_breadth,
                    benchmark_drawdown_pct,
                    analyst_weights_json,
                    ticker_penalties_json,
                    reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.created_at,
                    snapshot.profile,
                    snapshot.benchmark_ticker,
                    snapshot.regime,
                    snapshot.risk_state,
                    1 if snapshot.trading_enabled else 0,
                    snapshot.deployment_ratio,
                    snapshot.min_cash_buffer,
                    snapshot.max_position_override,
                    snapshot.average_credibility,
                    snapshot.average_conviction,
                    snapshot.bullish_breadth,
                    snapshot.benchmark_drawdown_pct,
                    json.dumps(snapshot.analyst_weights, sort_keys=True),
                    json.dumps(snapshot.ticker_penalties, sort_keys=True),
                    json.dumps(snapshot.reasons),
                ),
            )

    def latest_snapshot(self) -> Optional[GovernorSnapshot]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM governor_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        if not row:
            return None

        return GovernorSnapshot(
            created_at=row["created_at"],
            profile=row["profile"],
            benchmark_ticker=row["benchmark_ticker"],
            regime=row["regime"],
            risk_state=row["risk_state"],
            trading_enabled=bool(row["trading_enabled"]),
            deployment_ratio=float(row["deployment_ratio"]),
            min_cash_buffer=float(row["min_cash_buffer"]),
            max_position_override=row["max_position_override"],
            average_credibility=float(row["average_credibility"]),
            average_conviction=float(row["average_conviction"]),
            bullish_breadth=float(row["bullish_breadth"]),
            benchmark_drawdown_pct=float(row["benchmark_drawdown_pct"]),
            analyst_weights=json.loads(row["analyst_weights_json"]),
            ticker_penalties=json.loads(row["ticker_penalties_json"]),
            reasons=json.loads(row["reasons_json"]),
        )


class PortfolioGovernor:
    """Computes preservation-first capital controls from market state and analyst quality."""

    def __init__(
        self,
        *,
        profile: str = "preservation",
        store: Optional[GovernorStore] = None,
    ) -> None:
        self.profile = profile
        self.store = store or GovernorStore()

    def evaluate(
        self,
        *,
        selected_analysts: Sequence[str],
        aggregated_scores: Optional[Mapping[str, float]] = None,
        ticker_markets: Optional[Mapping[str, str]] = None,
        max_position: float = 0.25,
        benchmark_ticker: Optional[str] = None,
        scorecard_result: Optional[RegimeScorecardResult] = None,
        benchmark_drawdown_pct: Optional[float] = None,
        persist: bool = True,
    ) -> GovernorDecision:
        selected = [name for name in selected_analysts if name]
        resolved_benchmark = benchmark_ticker or resolve_benchmark_ticker(dict(ticker_markets or {}))

        scorecard_result = scorecard_result or build_regime_scorecard(
            analyst_names=list(selected) or None,
            benchmark_ticker=resolved_benchmark,
            ticker_markets=dict(ticker_markets or {}),
        )
        if scorecard_result.benchmark_ticker:
            resolved_benchmark = scorecard_result.benchmark_ticker

        current_regime = self._current_regime(
            benchmark_ticker=resolved_benchmark,
            fallback=scorecard_result.regime_by_date,
        )
        current_drawdown_pct = benchmark_drawdown_pct
        if current_drawdown_pct is None:
            current_drawdown_pct = self._benchmark_drawdown_pct(resolved_benchmark)

        analyst_weights, analyst_scores = self._analyst_weights_for_regime(
            selected_analysts=selected,
            scorecard_result=scorecard_result,
            regime=current_regime,
        )

        average_credibility = (
            sum(score.credibility for score in analyst_scores) / len(analyst_scores)
            if analyst_scores
            else 1.0
        )
        average_conviction = (
            sum(score.conviction_rate for score in analyst_scores) / len(analyst_scores)
            if analyst_scores
            else 0.0
        )
        bullish_breadth = self._compute_breadth(aggregated_scores)
        ticker_penalties = self._ticker_penalties(aggregated_scores, current_regime)

        risk_state = "normal"
        trading_enabled = True
        deployment_ratio = 1.0
        min_cash_buffer = 0.10
        max_position_override: float | None = None
        reasons: list[str] = []

        if current_drawdown_pct <= -12.0:
            risk_state = "halted"
            trading_enabled = False
            deployment_ratio = 0.0
            min_cash_buffer = 1.0
            max_position_override = 0.0
            reasons.append(f"Benchmark drawdown {current_drawdown_pct:.1f}% breached the halt threshold.")
        else:
            if current_regime == "high_vol":
                risk_state = "warning"
                deployment_ratio = min(deployment_ratio, 0.50)
                min_cash_buffer = max(min_cash_buffer, 0.35)
                max_position_override = min(max_position, 0.12)
                reasons.append("High-volatility regime detected; throttle deployment and concentration.")
            elif current_regime == "trend_down":
                risk_state = "warning"
                deployment_ratio = min(deployment_ratio, 0.65)
                min_cash_buffer = max(min_cash_buffer, 0.25)
                max_position_override = min(max_position, 0.15)
                reasons.append("Down-trend regime detected; preserve cash and tighten position caps.")

            if average_credibility < 0.90:
                risk_state = "warning"
                deployment_ratio = min(deployment_ratio, 0.60)
                min_cash_buffer = max(min_cash_buffer, 0.25)
                max_position_override = min(max_position_override or max_position, 0.14)
                reasons.append("Analyst credibility is below neutral; reduce fresh capital at risk.")

            if bullish_breadth < 0.20 and aggregated_scores:
                risk_state = "warning"
                deployment_ratio = min(deployment_ratio, 0.45)
                min_cash_buffer = max(min_cash_buffer, 0.35)
                max_position_override = min(max_position_override or max_position, 0.12)
                reasons.append("Bullish breadth is narrow; restrict new buying.")

            if average_conviction < 0.20 and analyst_scores:
                deployment_ratio = min(deployment_ratio, 0.75)
                min_cash_buffer = max(min_cash_buffer, 0.20)
                reasons.append("Analyst conviction is weak; keep a larger cash buffer.")

        if not reasons:
            reasons.append("Conditions are acceptable for normal deployment.")

        decision = GovernorDecision(
            profile=self.profile,
            benchmark_ticker=resolved_benchmark,
            regime=current_regime,
            risk_state=risk_state,
            trading_enabled=trading_enabled,
            deployment_ratio=_clamp(deployment_ratio, 0.0, 1.0),
            analyst_weights=analyst_weights,
            ticker_penalties=ticker_penalties,
            max_position_override=max_position_override,
            min_cash_buffer=_clamp(min_cash_buffer, 0.0, 1.0),
            reasons=reasons,
            average_credibility=average_credibility,
            average_conviction=average_conviction,
            bullish_breadth=bullish_breadth,
            benchmark_drawdown_pct=current_drawdown_pct,
            analyst_scores=analyst_scores,
        )
        if persist:
            self.store.save_snapshot(GovernorSnapshot.from_decision(decision))
        return decision

    def apply_to_target_weights(
        self,
        target_weights: Mapping[str, float],
        decision: GovernorDecision,
    ) -> dict[str, float]:
        investable_ratio = min(
            decision.deployment_ratio,
            max(0.0, 1.0 - decision.min_cash_buffer),
        )
        adjusted: dict[str, float] = {}
        for ticker, weight in target_weights.items():
            penalty = decision.ticker_penalties.get(ticker, 1.0)
            adjusted[ticker] = max(weight, 0.0) * penalty * investable_ratio
        return adjusted

    def apply_to_recommendations(
        self,
        recommendations: Sequence[Mapping[str, Any]],
        decision: GovernorDecision,
    ) -> list[dict[str, Any]]:
        adjusted: list[dict[str, Any]] = []
        for rec in recommendations:
            updated = dict(rec)
            action = str(updated.get("action", "HOLD")).upper()
            current_shares = float(updated.get("current_shares", 0.0) or 0.0)
            target_shares = float(updated.get("target_shares", 0.0) or 0.0)

            if not decision.trading_enabled and action in {"ADD", "INCREASE"}:
                updated["action"] = "HOLD"
                updated["target_shares"] = current_shares
                updated["target_weight"] = updated.get("current_weight", 0.0)
                updated["value_delta"] = 0.0
                updated["reasoning"] = f"{updated.get('reasoning', '')} Governor blocked fresh buying.".strip()

            adjusted.append(updated)
        return adjusted

    def apply_to_backtest_decisions(
        self,
        decisions: Mapping[str, Mapping[str, Any]],
        decision: GovernorDecision,
    ) -> dict[str, dict[str, Any]]:
        adjusted: dict[str, dict[str, Any]] = {}
        for ticker, payload in decisions.items():
            updated = dict(payload)
            action = str(updated.get("action", "hold")).lower()
            quantity = float(updated.get("quantity", 0.0) or 0.0)

            if action in {"buy", "short"}:
                if not decision.trading_enabled:
                    updated["action"] = "hold"
                    updated["quantity"] = 0.0
                else:
                    scaled_qty = int(quantity * decision.deployment_ratio)
                    updated["quantity"] = max(scaled_qty, 0)
                    if updated["quantity"] == 0:
                        updated["action"] = "hold"

            adjusted[ticker] = updated
        return adjusted

    def _analyst_weights_for_regime(
        self,
        *,
        selected_analysts: Sequence[str],
        scorecard_result: RegimeScorecardResult,
        regime: RegimeLabel,
    ) -> tuple[dict[str, float], list[AnalystRegimeScore]]:
        overall_lookup = {score.analyst_name: score for score in scorecard_result.analyst_scores}
        regime_lookup = {
            score.analyst_name: score
            for score in scorecard_result.regime_scores.get(regime, [])
        }

        analyst_weights: dict[str, float] = {}
        analyst_scores: list[AnalystRegimeScore] = []
        for analyst_name in selected_analysts:
            score = regime_lookup.get(analyst_name) or overall_lookup.get(analyst_name)
            if score is None:
                analyst_weights[analyst_name] = 0.85
                continue

            weight = score.credibility
            if score.avg_alpha < 0:
                weight *= 0.80
            if score.conviction_rate < 0.20:
                weight *= 0.90
            if regime == "high_vol" and score.hit_rate < 0.55:
                weight *= 0.85
            if regime == "trend_down" and score.avg_alpha > 0:
                weight *= 1.05

            bounded = _clamp(weight, 0.35, 1.75)
            analyst_weights[analyst_name] = bounded
            analyst_scores.append(
                AnalystRegimeScore(
                    analyst_name=score.analyst_name,
                    display_name=score.display_name,
                    credibility=score.credibility,
                    hit_rate=score.hit_rate,
                    avg_alpha=score.avg_alpha,
                    conviction_rate=score.conviction_rate,
                    weight=bounded,
                    regime=regime,
                )
            )

        return analyst_weights, analyst_scores

    def _benchmark_drawdown_pct(self, benchmark_ticker: str) -> float:
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")
        price_index = build_price_index([benchmark_ticker], start, end)
        entries = price_index.get(benchmark_ticker, [])
        if not entries:
            return 0.0

        peak = entries[0][1]
        drawdown = 0.0
        for _, close in entries:
            peak = max(peak, close)
            if peak > 0:
                drawdown = min(drawdown, (close - peak) / peak)
        return drawdown * 100.0

    def _current_regime(
        self,
        *,
        benchmark_ticker: str,
        fallback: Mapping[str, RegimeLabel],
    ) -> RegimeLabel:
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")
        regime_by_date = build_regime_map(
            benchmark_ticker=benchmark_ticker,
            start=start,
            end=end,
        )
        if regime_by_date:
            latest_date = max(regime_by_date)
            return regime_by_date[latest_date]
        if fallback:
            latest_date = max(fallback)
            return fallback[latest_date]
        return "trend_up"

    def _compute_breadth(self, aggregated_scores: Optional[Mapping[str, float]]) -> float:
        if not aggregated_scores:
            return 0.0
        qualified = [score for score in aggregated_scores.values() if score > 0.10]
        return len(qualified) / len(aggregated_scores) if aggregated_scores else 0.0

    def _ticker_penalties(
        self,
        aggregated_scores: Optional[Mapping[str, float]],
        regime: RegimeLabel,
    ) -> dict[str, float]:
        if not aggregated_scores:
            return {}

        ranked = sorted(aggregated_scores.items(), key=lambda item: item[1], reverse=True)
        penalties: dict[str, float] = {}
        top_count = min(3, len(ranked))
        for idx, (ticker, score) in enumerate(ranked):
            penalty = 1.0
            if regime == "high_vol" and idx < top_count and score > 0.50:
                penalty = 0.90
            elif regime == "trend_down" and idx < top_count and score > 0.40:
                penalty = 0.92
            penalties[ticker] = penalty
        return penalties


def format_governor_summary(decision: GovernorDecision) -> list[str]:
    """Render a compact, human-readable governor summary."""
    lines = [
        f"Profile: {decision.profile}",
        f"State: {decision.risk_state} | Regime: {decision.regime} | Benchmark: {decision.benchmark_ticker}",
        (
            "Trading: "
            f"{'enabled' if decision.trading_enabled else 'blocked'} | "
            f"Deployment: {decision.deployment_ratio:.0%} | "
            f"Cash buffer: {decision.min_cash_buffer:.0%}"
        ),
        (
            "Quality: "
            f"credibility {decision.average_credibility:.2f}, "
            f"conviction {decision.average_conviction:.0%}, "
            f"breadth {decision.bullish_breadth:.0%}, "
            f"benchmark DD {decision.benchmark_drawdown_pct:.1f}%"
        ),
    ]
    lines.extend(f"- {reason}" for reason in decision.reasons)
    return lines


def snapshot_to_dict(snapshot: GovernorSnapshot) -> dict[str, Any]:
    return asdict(snapshot)
