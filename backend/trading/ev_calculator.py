"""Expected value calculation and bracket scanning for trade signal generation.

This is the mathematical core of the trading engine. For each bracket in each
city, it calculates expected value for both YES and NO sides, accounting for
Kalshi fees. Only trades with positive EV above the user's threshold are
generated as TradeSignal objects.

CRITICAL: All prices are in CENTS (integers). EV output is in DOLLARS (float).
Fee calculation returns CENTS (int).

Fee structure (Kalshi fee schedule, effective Feb 5, 2026):
    - Taker fee = ceil(0.07 * C * P * (1-P)), where P = contract price in dollars
    - The formula is symmetric: P*(1-P) is the same for YES at P and NO at (1-P)
    - For conservative EV, we subtract fees unconditionally (overestimates cost)

Usage:
    from backend.trading.ev_calculator import scan_all_brackets

    signals = scan_all_brackets(
        prediction=bracket_prediction,
        market_prices={"52° to 53°F": 22, "54° to 55°F": 35},
        market_tickers={"52° to 53°F": "KXHIGHNY-26FEB18-T52", ...},
        min_ev_threshold=0.05,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.common.logging import get_logger
from backend.common.schemas import BracketPrediction, TradeSignal

logger = get_logger("TRADING")
ET = ZoneInfo("America/New_York")


@dataclass
class GuardrailSettings:
    """Configuration for trading engine guardrails.

    These settings prevent the model from overriding market consensus
    by blending model probabilities with market prices and capping
    extreme divergences.

    Attributes:
        model_weight: Weight for model prob in blend (0.0-1.0). Default 0.4
            means 40% model, 60% market.
        max_model_market_divergence: Maximum absolute difference allowed
            between model prob and market prob before clamping (0.0-0.5).
        min_market_prob_for_yes: Minimum market probability (YES price / 100)
            required to consider a YES trade. Filters out cheap longshots.
    """

    model_weight: float = 0.4
    max_model_market_divergence: float = 0.25
    min_market_prob_for_yes: float = 0.15


def apply_guardrails(
    model_prob: float,
    market_price_cents: int,
    side: str,
    settings: GuardrailSettings | None = None,
) -> tuple[float | None, str | None]:
    """Apply guardrails to model probability before EV calculation.

    Three guardrails applied in order:
    1. Market probability floor — skip YES trades on cheap brackets
    2. Divergence cap — clamp model prob within ±max_divergence of market
    3. Blending — weighted average of capped model and market probability

    Args:
        model_prob: Raw model probability for the bracket (0.0-1.0).
        market_price_cents: Kalshi market YES price in cents (1-99).
        side: "yes" or "no".
        settings: Guardrail configuration. None disables all guardrails.

    Returns:
        Tuple of (blended_probability, skip_reason).
        If skip_reason is not None, the trade should be skipped.
    """
    if settings is None:
        return model_prob, None

    market_prob_yes = market_price_cents / 100

    # Guardrail 3: Minimum market probability floor for YES
    if side == "yes" and market_prob_yes < settings.min_market_prob_for_yes:
        return None, "market_floor"

    # Guardrail 2: Cap model divergence from market
    capped = max(
        market_prob_yes - settings.max_model_market_divergence,
        min(model_prob, market_prob_yes + settings.max_model_market_divergence),
    )
    # Clamp to valid probability range
    capped = max(0.001, min(0.999, capped))

    # Guardrail 1: Blend capped model with market
    blended = settings.model_weight * capped + (1.0 - settings.model_weight) * market_prob_yes
    # Clamp final result
    blended = max(0.001, min(0.999, blended))

    return round(blended, 6), None


def estimate_fees(price_cents: int, side: str) -> int:
    """Estimate Kalshi taker fees for a single contract in CENTS.

    Kalshi fee formula (effective Feb 5, 2026):
        fee = ceil(0.07 * C * P * (1-P))

    Where P = contract price in dollars, C = contract count.
    The formula is symmetric: P*(1-P) is the same for YES at P and NO at (1-P),
    so the fee is identical regardless of side. We keep the side parameter for
    API compatibility but it doesn't affect the result.

    Args:
        price_cents: Market YES price in cents (1-99).
        side: "yes" or "no" (kept for API compatibility; fee is side-agnostic).

    Returns:
        Estimated fee in CENTS per contract (int, minimum 1).

    Raises:
        ValueError: If price_cents is outside [1, 99] or side is invalid.
    """
    if not (1 <= price_cents <= 99):
        msg = f"price_cents must be 1-99, got {price_cents}"
        raise ValueError(msg)
    if side not in ("yes", "no"):
        msg = f"side must be 'yes' or 'no', got {side!r}"
        raise ValueError(msg)

    # Kalshi: ceil(0.07 * 1 * P * (1-P)), convert to cents: ceil(7 * P * (1-P))
    p = price_cents / 100
    fee_cents = math.ceil(7 * p * (1 - p))
    return max(1, fee_cents)


def calculate_ev(
    model_prob: float,
    market_price_cents: int,
    side: str,
) -> float:
    """Calculate expected value for a potential trade.

    Uses the conservative approach: fees are subtracted unconditionally
    (not only on wins). This slightly underestimates true EV, which is
    safer -- we'd rather miss a marginal trade than take a bad one.

    Args:
        model_prob: Our model's probability for the bracket (0.0 to 1.0).
        market_price_cents: Kalshi market YES price in CENTS (1-99).
        side: "yes" or "no".

    Returns:
        Expected value in DOLLARS (positive = profitable).

    Raises:
        ValueError: If model_prob is outside [0.0, 1.0] or inputs invalid.
    """
    if not (0.0 <= model_prob <= 1.0):
        msg = f"model_prob must be 0.0-1.0, got {model_prob}"
        raise ValueError(msg)

    if side == "yes":
        prob_win = model_prob
        cost_dollars = market_price_cents / 100
    elif side == "no":
        prob_win = 1.0 - model_prob
        cost_dollars = (100 - market_price_cents) / 100
    else:
        msg = f"side must be 'yes' or 'no', got {side!r}"
        raise ValueError(msg)

    fee_cents = estimate_fees(market_price_cents, side)
    fee_dollars = fee_cents / 100

    ev = (prob_win * 1.00) - cost_dollars - fee_dollars
    return round(ev, 4)


def scan_bracket(
    bracket_label: str,
    bracket_probability: float,
    market_price_cents: int,
    min_ev_threshold: float,
    city: str,
    prediction_date: str,
    confidence: str,
    market_ticker: str,
    kelly_settings: object | None = None,
    bankroll_cents: int = 0,
    max_trade_size_cents: int = 100,
    guardrail_settings: GuardrailSettings | None = None,
) -> TradeSignal | None:
    """Scan a single bracket for trading opportunities on both YES and NO sides.

    Calculates EV for both sides and returns a TradeSignal for the better
    side if it meets the minimum threshold. If guardrails are enabled,
    probabilities are blended with market prices to prevent overconfident
    model bets. If Kelly sizing is enabled, the signal's quantity is sized
    optimally based on edge and bankroll.

    Args:
        bracket_label: Bracket label string (e.g., "53-54F").
        bracket_probability: Model probability for this bracket (0.0-1.0).
        market_price_cents: Current Kalshi YES price in cents.
        min_ev_threshold: Minimum EV in dollars to trigger a trade.
        city: City code (e.g., "NYC").
        prediction_date: Date string for the event.
        confidence: Model confidence level ("high", "medium", "low").
        market_ticker: Kalshi market ticker string.
        kelly_settings: KellySettings for position sizing (None = 1 contract).
        bankroll_cents: Total bankroll in cents for Kelly sizing.
        max_trade_size_cents: Max cost per trade from risk manager.
        guardrail_settings: GuardrailSettings for probability guardrails (None = raw model).

    Returns:
        TradeSignal if a +EV opportunity exists, None otherwise.
    """
    # Apply guardrails to get blended probabilities for both sides
    blended_yes, skip_yes = apply_guardrails(
        bracket_probability, market_price_cents, "yes", guardrail_settings
    )
    blended_no, skip_no = apply_guardrails(
        bracket_probability, market_price_cents, "no", guardrail_settings
    )

    # Log guardrail blocks
    if skip_yes is not None:
        try:
            from backend.common.metrics import GUARDRAIL_BLOCKED_TOTAL

            GUARDRAIL_BLOCKED_TOTAL.labels(reason=skip_yes).inc()
        except Exception:
            pass

    # Calculate EV using blended probabilities (or skip if blocked)
    ev_yes = (
        calculate_ev(blended_yes, market_price_cents, "yes") if blended_yes is not None else -999.0
    )
    ev_no = calculate_ev(blended_no, market_price_cents, "no") if blended_no is not None else -999.0

    logger.debug(
        "Bracket scan",
        extra={
            "data": {
                "city": city,
                "bracket": bracket_label,
                "model_prob": round(bracket_probability, 4),
                "blended_yes": round(blended_yes, 4) if blended_yes else None,
                "blended_no": round(blended_no, 4) if blended_no else None,
                "market_cents": market_price_cents,
                "ev_yes": ev_yes,
                "ev_no": ev_no,
                "skip_yes": skip_yes,
            }
        },
    )

    # Pick the better side if it meets the threshold
    best_side: str | None = None
    best_ev = 0.0
    best_blended: float | None = None

    if ev_yes >= ev_no and ev_yes >= min_ev_threshold:
        best_side = "yes"
        best_ev = ev_yes
        best_blended = blended_yes if guardrail_settings is not None else None
    elif ev_no > ev_yes and ev_no >= min_ev_threshold:
        best_side = "no"
        best_ev = ev_no
        best_blended = blended_no if guardrail_settings is not None else None

    if best_side is None:
        return None  # No trade opportunity

    # Calculate market probability from the perspective of the chosen side
    if best_side == "yes":
        market_prob = market_price_cents / 100
    else:
        market_prob = (100 - market_price_cents) / 100

    # Kelly Criterion position sizing (graceful degradation)
    # Use blended probability for Kelly edge calculation when guardrails are active
    kelly_prob = best_blended if best_blended is not None else bracket_probability
    quantity = 1
    if kelly_settings is not None and getattr(kelly_settings, "use_kelly_sizing", False):
        try:
            from backend.common.metrics import KELLY_CONTRACTS_HISTOGRAM, KELLY_SIZING_TOTAL
            from backend.trading.kelly import calculate_kelly_size

            result = calculate_kelly_size(
                model_prob=kelly_prob,
                price_cents=market_price_cents,
                side=best_side,
                bankroll_cents=bankroll_cents,
                settings=kelly_settings,
                max_trade_size_cents=max_trade_size_cents,
            )
            if result.optimal_quantity == 0:
                KELLY_SIZING_TOTAL.labels(city=city, outcome="no_edge").inc()
                logger.debug(
                    "Kelly says no edge — skipping trade",
                    extra={
                        "data": {
                            "city": city,
                            "bracket": bracket_label,
                            "kelly_fraction": result.raw_kelly_fraction,
                        }
                    },
                )
                return None
            quantity = result.optimal_quantity
            KELLY_SIZING_TOTAL.labels(city=city, outcome="sized").inc()
            KELLY_CONTRACTS_HISTOGRAM.observe(quantity)
        except Exception as exc:
            logger.warning(
                "Kelly sizing failed, falling back to 1 contract",
                extra={"data": {"error": str(exc), "city": city, "bracket": bracket_label}},
            )
            quantity = 1

    return TradeSignal(
        city=city,
        bracket=bracket_label,
        side=best_side,
        price_cents=market_price_cents,
        quantity=quantity,
        model_probability=bracket_probability,
        blended_probability=best_blended,
        market_probability=round(market_prob, 4),
        ev=best_ev,
        confidence=confidence,
        market_ticker=market_ticker,
        reasoning=_generate_signal_reasoning(
            bracket_label,
            bracket_probability,
            market_price_cents,
            best_side,
            best_ev,
            best_blended,
        ),
    )


def scan_all_brackets(
    prediction: BracketPrediction,
    market_prices: dict[str, int],
    market_tickers: dict[str, str],
    min_ev_threshold: float,
    kelly_settings: object | None = None,
    bankroll_cents: int = 0,
    max_trade_size_cents: int = 100,
    guardrail_settings: GuardrailSettings | None = None,
) -> list[TradeSignal]:
    """Scan all brackets for a city and return all +EV trade signals.

    Args:
        prediction: Full bracket prediction for one city.
        market_prices: Mapping of bracket label to current YES price in cents.
        market_tickers: Mapping of bracket label to Kalshi market ticker string.
        min_ev_threshold: Minimum EV in dollars to trigger a trade.
        kelly_settings: KellySettings for position sizing (None = 1 contract).
        bankroll_cents: Total bankroll in cents for Kelly sizing.
        max_trade_size_cents: Max cost per trade from risk manager.
        guardrail_settings: GuardrailSettings for probability guardrails (None = raw model).

    Returns:
        List of TradeSignal objects, sorted by EV descending (best first).
    """
    signals: list[TradeSignal] = []

    for bracket in prediction.brackets:
        price = market_prices.get(bracket.bracket_label)
        if price is None:
            logger.warning(
                "No market price for bracket",
                extra={
                    "data": {
                        "city": prediction.city,
                        "bracket": bracket.bracket_label,
                    }
                },
            )
            continue

        ticker = market_tickers.get(bracket.bracket_label)
        if ticker is None:
            logger.warning(
                "No market ticker for bracket",
                extra={
                    "data": {
                        "city": prediction.city,
                        "bracket": bracket.bracket_label,
                    }
                },
            )
            continue

        signal = scan_bracket(
            bracket_label=bracket.bracket_label,
            bracket_probability=bracket.probability,
            market_price_cents=price,
            min_ev_threshold=min_ev_threshold,
            city=prediction.city,
            prediction_date=str(prediction.date),
            confidence=prediction.confidence,
            market_ticker=ticker,
            kelly_settings=kelly_settings,
            bankroll_cents=bankroll_cents,
            max_trade_size_cents=max_trade_size_cents,
            guardrail_settings=guardrail_settings,
        )
        if signal is not None:
            signals.append(signal)

    # Sort by EV descending -- best opportunity first
    signals.sort(key=lambda s: s.ev, reverse=True)

    logger.info(
        "Bracket scan complete",
        extra={
            "data": {
                "city": prediction.city,
                "total_brackets": len(prediction.brackets),
                "signals_found": len(signals),
            }
        },
    )
    return signals


def validate_predictions(predictions: list[BracketPrediction]) -> bool:
    """Validate prediction data before trading on it.

    Returns True if ALL predictions are valid. Logs specific errors.
    If any prediction is invalid, returns False -- halt trading for this cycle.

    Checks:
        - Probabilities sum to ~1.0 (within 0.95-1.05 tolerance)
        - No NaN or negative probabilities
        - Exactly 6 brackets per prediction
        - Data freshness (predictions must be less than 2 hours old)

    Args:
        predictions: List of BracketPrediction objects to validate.

    Returns:
        True if all predictions pass validation, False otherwise.
    """
    for pred in predictions:
        # Probabilities must sum to ~1.0 (allow small floating point error)
        total = sum(b.probability for b in pred.brackets)
        if not (0.95 <= total <= 1.05):
            logger.error(
                "Bracket probabilities do not sum to 1.0",
                extra={"data": {"city": pred.city, "total": round(total, 4)}},
            )
            return False

        # No NaN or negative probabilities
        for b in pred.brackets:
            if math.isnan(b.probability) or b.probability < 0:
                logger.error(
                    "Invalid probability value",
                    extra={
                        "data": {
                            "city": pred.city,
                            "bracket": b.bracket_label,
                            "probability": b.probability,
                        }
                    },
                )
                return False

        # Must have exactly 6 brackets
        if len(pred.brackets) != 6:
            logger.error(
                "Expected 6 brackets",
                extra={"data": {"city": pred.city, "count": len(pred.brackets)}},
            )
            return False

        # Data freshness check -- predictions older than 2 hours are stale
        now = datetime.now(ET)
        generated = pred.generated_at
        # Handle timezone-naive datetimes by treating them as UTC
        if generated.tzinfo is None:
            from datetime import UTC

            generated = generated.replace(tzinfo=UTC)
        age = now - generated.astimezone(ET)
        if age > timedelta(hours=2):
            logger.warning(
                "Stale predictions detected",
                extra={
                    "data": {
                        "city": pred.city,
                        "age_hours": round(age.total_seconds() / 3600, 2),
                    }
                },
            )
            return False

    return True


def validate_market_prices(prices: dict[str, int]) -> dict[str, int]:
    """Validate market prices and return only valid ones.

    Filters out brackets with invalid prices (non-integer, zero, or out of
    range) instead of rejecting the entire city.  Tail brackets often have
    zero liquidity (price 0) on Kalshi — this is normal and should not
    block trading on other brackets that DO have valid prices.

    Args:
        prices: Mapping of bracket label to YES price in cents.

    Returns:
        Dict of bracket labels with valid prices (integers in [1, 99]).
        Empty dict if no brackets have valid prices.
    """
    valid: dict[str, int] = {}
    for label, price in prices.items():
        if not isinstance(price, int):
            logger.warning(
                "Market price is not an integer — skipping bracket",
                extra={"data": {"bracket": label, "price": price}},
            )
            continue
        if not (1 <= price <= 99):
            logger.debug(
                "Market price out of range — skipping bracket",
                extra={"data": {"bracket": label, "price_cents": price}},
            )
            continue
        valid[label] = price
    if len(valid) < len(prices):
        logger.info(
            "Filtered invalid market prices",
            extra={
                "data": {
                    "total_brackets": len(prices),
                    "valid_brackets": len(valid),
                    "skipped": len(prices) - len(valid),
                }
            },
        )
    return valid


def _generate_signal_reasoning(
    bracket_label: str,
    bracket_prob: float,
    market_price_cents: int,
    side: str,
    ev: float,
    blended_prob: float | None = None,
) -> str:
    """Generate human-readable reasoning for a trade signal.

    Args:
        bracket_label: The bracket label (e.g., "53-54F").
        bracket_prob: Raw model probability for the bracket.
        market_price_cents: Current YES price in cents.
        side: The trade side ("yes" or "no").
        ev: The calculated EV in dollars.
        blended_prob: Post-guardrail blended probability, or None.

    Returns:
        A reasoning string suitable for display.
    """
    model_pct = bracket_prob * 100
    market_pct = market_price_cents if side == "yes" else 100 - market_price_cents

    if blended_prob is not None:
        blended_pct = blended_prob * 100
        edge = blended_pct - market_pct
        return (
            f"Model: {model_pct:.1f}% → Blended: {blended_pct:.1f}% vs Market: {market_pct}% "
            f"({'+' if edge > 0 else ''}{edge:.1f}% edge). "
            f"EV: ${ev:+.4f} per contract on {side.upper()} side."
        )

    edge = model_pct - market_pct
    return (
        f"Model: {model_pct:.1f}% vs Market: {market_pct}% "
        f"({'+' if edge > 0 else ''}{edge:.1f}% edge). "
        f"EV: ${ev:+.4f} per contract on {side.upper()} side."
    )
