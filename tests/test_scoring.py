from app.scoring import (
    compute_round_amount_score,
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


def _amounts(*values):
    return [{"amount": v} for v in values]


def test_round_amount_zero_when_no_payments():
    assert compute_round_amount_score([]) == 0


def test_round_amount_zero_with_too_few_payments():
    assert compute_round_amount_score(_amounts("500", "1000")) == 0


def test_round_amount_zero_for_organic_amounts():
    assert compute_round_amount_score(
        _amounts("12.34", "87.5", "431.21", "9.99")) == 0


def test_round_amount_full_score_when_every_payment_is_round():
    assert compute_round_amount_score(
        _amounts("100", "500", "1000", "2500")) == 10


def test_round_amount_scales_between_half_and_all():
    # 3 of 4 round -> share 0.75 -> halfway between 0 and 10.
    assert compute_round_amount_score(
        _amounts("100", "200", "300", "12.5")) == 5


def test_round_amount_half_round_scores_zero():
    assert compute_round_amount_score(
        _amounts("100", "200", "12.5", "7.3")) == 0


def test_round_amount_ignores_small_round_numbers():
    # 10 and 50 are round-looking but below the 100 threshold.
    assert compute_round_amount_score(_amounts("10", "50", "20", "30")) == 0


def test_round_amount_handles_stellar_seven_decimal_format():
    assert compute_round_amount_score(
        _amounts("500.0000000", "1000.0000000", "100.0000000")) == 10


def test_round_amount_skips_missing_invalid_and_non_positive():
    ops = [
        {"amount": "100"}, {"amount": "200"}, {"amount": "300"},
        {"other": "x"}, {"amount": "abc"}, {"amount": "-500"},
        {"amount": "0"}, {"amount": "NaN"},
    ]
    assert compute_round_amount_score(ops) == 10


def test_risk_score_includes_round_amounts():
    # Old account, spread out in time, different counterparties: the only
    # difference between the two lists is whether the amounts are round.
    def ops(amount):
        return [
            {"created_at": f"2026-05-0{day}T00:00:00Z", "to": f"G{day}",
             "amount": amount}
            for day in (1, 2, 3, 4)
        ]

    assert (compute_risk_score(ops("500"), now=NOW)
            - compute_risk_score(ops("12.5"), now=NOW)) == 10


def test_risk_score_stays_capped_at_100_with_round_amounts():
    ops = [{"created_at": "2026-06-01T11:00:00Z", "to": "GX", "amount": "500"}
           for _ in range(10)]
    assert compute_risk_score(ops, now=NOW) == 100
