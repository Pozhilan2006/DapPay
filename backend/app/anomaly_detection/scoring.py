"""Scoring logic for anomaly severity."""


def score_anomaly(anomaly: dict) -> float:
    return float(anomaly.get("score", 0.0))
