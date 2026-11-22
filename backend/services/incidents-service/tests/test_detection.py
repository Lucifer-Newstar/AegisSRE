from incidents_service.detection import detect


def test_warmup_is_explicit() -> None:
    assert not detect([1.0] * 11, 100).ready


def test_constant_baseline_detects_and_recovers() -> None:
    baseline = [0.1] * 20
    assert detect(baseline, 4).anomalous
    assert not detect(baseline, 0.101).anomalous


def test_if_and_statistical_scores_are_reproducible() -> None:
    baseline = [0.09, 0.1, 0.11] * 10
    a = detect(baseline, 2)
    assert a == detect(baseline, 2)
    assert a.anomalous and a.isolation_score < 0 and a.score > 0.9


def test_one_sided_latency_does_not_alert_on_improvement() -> None:
    assert not detect([10.0] * 20, 1.0, two_sided=False).anomalous
    assert detect([10.0] * 20, 1.0, two_sided=True).anomalous
