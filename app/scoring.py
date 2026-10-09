"""
Risk scoring heuristics. Kept as pure functions (no I/O) so they're
directly unit-testable without needing a live Horizon connection.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _parse_time(op: dict) -> datetime | None:
    ts = op.get("created_at")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_tx_velocity_score(operations: list[dict]) -> int:
    """
    Scores 0-40 based on how tightly clustered recent operations are in
    time. Many operations in a short window is treated as more suspicious
    than the same count spread over weeks.
    """
    times = sorted(t for t in (_parse_time(op) for op in operations) if t)
    if len(times) < 2:
        return 0

    span_seconds = (times[-1] - times[0]).total_seconds()
    if span_seconds <= 0:
        span_seconds = 1

    ops_per_hour = (len(times) / span_seconds) * 3600
    # Cap the contribution at 40 points; scale linearly up to 20 ops/hour.
    return min(40, int((ops_per_hour / 20) * 40))


def compute_counterparty_diversity_score(operations: list[dict]) -> int:
    """
    Scores 0-30 based on counterparty concentration. Many operations with
    very few distinct counterparties (a common laundering/wash-trading
    pattern) scores higher than diverse, organic-looking activity.
    """
    counterparties = [
        op.get("to") or op.get("from") or op.get("source_account")
        for op in operations
        if op.get("to") or op.get("from") or op.get("source_account")
    ]
    if not counterparties:
        return 0

    counts = Counter(counterparties)
    top_share = counts.most_common(1)[0][1] / len(counterparties)
    # top_share close to 1.0 (everything to/from one address) scores high.
    return int(top_share * 30)


def compute_volume_anomaly_score(operations: list[dict]) -> int:
    """
    Scores 0-30 based on payment volume variance. A few very large
    payments among mostly small ones raises the score.
    """
    amounts = []
    for op in operations:
        raw = op.get("amount")
        if raw is None:
            continue
        try:
            amounts.append(float(raw))
        except (TypeError, ValueError):
            continue

    if len(amounts) < 2:
        return 0

    amounts.sort()
    median = amounts[len(amounts) // 2]
    largest = amounts[-1]
    if median <= 0:
        return 30 if largest > 0 else 0

    ratio = largest / median
    if ratio <= 1:
        return 0
    # ratio of 1 (uniform) -> 0 points; ratio of 20+ -> full 30 points.
    return min(30, int(((ratio - 1) / 19) * 30))


def compute_account_age_score(
    operations: list[dict], now: datetime | None = None
) -> int:
    """
    Scores 0-20 based on how new the account looks. Brand-new accounts are
    a common trait of throwaway addresses used for fraud, so a very recent
    first operation scores higher than an established account.

    The age is measured from the oldest operation we were given, so for
    accounts with more history than the fetch limit this can understate
    the real age. That errs on the side of a slightly higher score, never
    a lower one. No operations at all scores 0 ("no history" is handled
    by the other heuristics and by the caller).
    """
    times = [t for t in (_parse_time(op) for op in operations) if t]
    if not times:
        return 0

    now = now or datetime.now(timezone.utc)
    age_days = (now - min(times)).total_seconds() / 86400
    if age_days < 0:
        # Timestamps in the future are unreliable; don't penalise them.
        return 0
    if age_days < 1:
        return 20
    if age_days < 7:
        return 10
    if age_days < 30:
        return 5
    return 0


ROUND_AMOUNT_UNIT = Decimal(100)
ROUND_AMOUNT_MIN_PAYMENTS = 3


def compute_round_amount_score(operations: list[dict]) -> int:
    """
    Scores 0-10 based on how many payments are suspiciously round (a
    multiple of 100, at least 100). Structured or scripted transfers often
    use round figures, while organic payments rarely do.

    Needs at least ROUND_AMOUNT_MIN_PAYMENTS valid amounts, otherwise 0.
    Up to half of the payments being round scores 0 (that can happen by
    chance); the score then rises linearly to 10 when every payment is round.
    """
    amounts = []
    for op in operations:
        raw = op.get("amount")
        if raw is None:
            continue
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            continue
        if value.is_finite() and value > 0:
            amounts.append(value)

    if len(amounts) < ROUND_AMOUNT_MIN_PAYMENTS:
        return 0

    round_count = sum(
        1 for a in amounts if a >= ROUND_AMOUNT_UNIT and a % ROUND_AMOUNT_UNIT == 0
    )
    share = round_count / len(amounts)
    if share <= 0.5:
        return 0
    return min(10, int((share - 0.5) / 0.5 * 10))


def compute_risk_score(operations: list[dict], now: datetime | None = None) -> int:
    """Combine all heuristics into a single 0-100 score (clamped)."""
    score = (
        compute_tx_velocity_score(operations)
        + compute_counterparty_diversity_score(operations)
        + compute_volume_anomaly_score(operations)
        + compute_account_age_score(operations, now=now)
        + compute_round_amount_score(operations)
    )
    return max(0, min(100, score))
