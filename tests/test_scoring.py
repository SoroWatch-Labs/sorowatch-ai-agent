from app.scoring import (
    compute_tx_velocity_score,
    compute_counterparty_diversity_score,
    compute_volume_anomaly_score,
    compute_account_age_score,
    compute_risk_score,
)
from datetime import datetime, timezone


def test_velocity_score_zero_for_no_operations():
    assert compute_tx_velocity_score([]) == 0


def test_velocity_score_zero_for_single_operation():
    assert compute_tx_velocity_score(
        [{"created_at": "2026-01-01T00:00:00Z"}]) == 0


def test_velocity_score_high_for_rapid_operations():
    ops = [
        {"created_at": "2026-01-01T00:00:00Z"},
        {"created_at": "2026-01-01T00:01:00Z"},
        {"created_at": "2026-01-01T00:02:00Z"},
        {"created_at": "2026-01-01T00:03:00Z"},
        {"created_at": "2026-01-01T00:04:00Z"},
    ]
    score = compute_tx_velocity_score(ops)
    assert score > 0


def test_velocity_score_low_for_spread_out_operations():
    ops = [
        {"created_at": "2026-01-01T00:00:00Z"},
        {"created_at": "2026-01-08T00:00:00Z"},
    ]
    score = compute_tx_velocity_score(ops)
    assert score == 0


def test_counterparty_diversity_zero_for_no_operations():
    assert compute_counterparty_diversity_score([]) == 0


def test_counterparty_diversity_high_for_single_counterparty():
    ops = [{"to": "GABC"} for _ in range(10)]
    score = compute_counterparty_diversity_score(ops)
    assert score == 30


def test_counterparty_diversity_low_for_many_counterparties():
    ops = [{"to": f"GABC{i}"} for i in range(10)]
    score = compute_counterparty_diversity_score(ops)
    assert score <= 5


def test_volume_anomaly_zero_for_uniform_amounts():
    ops = [{"amount": "100"} for _ in range(5)]
    assert compute_volume_anomaly_score(ops) == 0


def test_volume_anomaly_high_for_outlier_payment():
    ops = [{"amount": "10"}, {"amount": "10"},
           {"amount": "10"}, {"amount": "5000"}]
    score = compute_volume_anomaly_score(ops)
    assert score > 0


def test_volume_anomaly_handles_missing_or_invalid_amounts():
    ops = [{"amount": "10"}, {"other_field": "x"}, {"amount": "not_a_number"}]
    # Should not raise, and should treat invalid entries as absent.
    score = compute_volume_anomaly_score(ops)
    assert isinstance(score, int)


def test_risk_score_combines_all_three_and_caps_at_100():
    ops = [
        {"created_at": "2026-01-01T00:00:00Z", "to": "GABC", "amount": "10"},
        {"created_at": "2026-01-01T00:00:10Z", "to": "GABC", "amount": "10"},
        {"created_at": "2026-01-01T00:00:20Z", "to": "GABC", "amount": "9999"},
    ]
    score = compute_risk_score(ops)
    assert 0 <= score <= 100


def test_risk_score_zero_for_empty_history():
    assert compute_risk_score([]) == 0


NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def test_account_age_zero_for_no_operations():
    assert compute_account_age_score([], now=NOW) == 0


def test_account_age_max_for_account_under_one_day_old():
    ops = [{"created_at": "2026-06-01T06:00:00Z"}]
    assert compute_account_age_score(ops, now=NOW) == 20


def test_account_age_medium_for_account_a_few_days_old():
    ops = [{"created_at": "2026-05-28T12:00:00Z"}]
    assert compute_account_age_score(ops, now=NOW) == 10


def test_account_age_low_for_account_a_few_weeks_old():
    ops = [{"created_at": "2026-05-10T12:00:00Z"}]
    assert compute_account_age_score(ops, now=NOW) == 5


def test_account_age_zero_for_established_account():
    ops = [{"created_at": "2025-01-01T00:00:00Z"}]
    assert compute_account_age_score(ops, now=NOW) == 0


def test_account_age_uses_oldest_operation():
    ops = [
        {"created_at": "2026-06-01T11:00:00Z"},
        {"created_at": "2025-01-01T00:00:00Z"},
    ]
    assert compute_account_age_score(ops, now=NOW) == 0


def test_account_age_ignores_future_and_unparseable_timestamps():
    assert compute_account_age_score(
        [{"created_at": "2027-01-01T00:00:00Z"}], now=NOW) == 0
    assert compute_account_age_score(
        [{"created_at": "not-a-date"}], now=NOW) == 0


def test_risk_score_includes_account_age_and_stays_capped():
    ops = [{"created_at": "2026-06-01T11:00:00Z", "to": "GX", "amount": "1"}]
    with_age = compute_risk_score(ops, now=NOW)
    without_age = compute_risk_score(
        ops, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert with_age - without_age == 20
    assert 0 <= with_age <= 100
