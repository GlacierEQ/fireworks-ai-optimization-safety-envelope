from __future__ import annotations

import pytest

from benchmark_evidence_adapter import BenchmarkEvidenceError, build_selection_payload
from optimization_safety_envelope import OptimizationSafetyEnvelope, OptimizationSafetyEnvelopeRequest


BUDGETS = {
    "coding": {"max_quality_drop": 0.03, "max_error_rate_increase": 0.05},
    "reasoning": {"max_quality_drop": 0.02, "max_error_rate_increase": 0.05},
}


def sample(variant: str, workload: str, latency: float, quality: float, error: bool = False):
    return {
        "variant_id": variant,
        "workload": workload,
        "latency_ms": latency,
        "quality_score": quality,
        "error": error,
    }


def test_raw_benchmark_samples_drive_canary_selection() -> None:
    rows = []
    for workload, baseline_quality, candidate_quality in (
        ("coding", 0.91, 0.90),
        ("reasoning", 0.94, 0.93),
    ):
        for _ in range(3):
            rows.append(sample("baseline", workload, 100.0, baseline_quality))
            rows.append(sample("optimized", workload, 82.0, candidate_quality))

    payload = build_selection_payload(
        rows,
        baseline_variant_id="baseline",
        workload_budgets=BUDGETS,
    )
    receipt = OptimizationSafetyEnvelope().evaluate(
        OptimizationSafetyEnvelopeRequest(subject_id="benchmark", payload=payload)
    )

    assert receipt.decision.value == "ALLOW"
    assert receipt.metrics["action"] == "CANARY"
    assert receipt.metrics["selected_variant_id"] == "optimized"
    assert payload["evidence"]["sample_count"] == 12


def test_benchmark_adapter_exposes_quality_regression_instead_of_hiding_it() -> None:
    rows = []
    for workload in BUDGETS:
        for _ in range(3):
            rows.append(sample("baseline", workload, 100.0, 0.95))
            rows.append(sample("fast-bad", workload, 70.0, 0.70))

    payload = build_selection_payload(rows, baseline_variant_id="baseline", workload_budgets=BUDGETS)
    receipt = OptimizationSafetyEnvelope().evaluate(
        OptimizationSafetyEnvelopeRequest(subject_id="benchmark", payload=payload)
    )

    assert receipt.decision.value == "REFUSE"
    assert "no_variant_inside_safety_envelope" in receipt.reasons


def test_adapter_refuses_missing_coverage_and_unknown_workloads() -> None:
    rows = [sample("baseline", "coding", 100.0, 0.9)] * 3
    rows += [sample("optimized", "coding", 80.0, 0.9)] * 3
    with pytest.raises(BenchmarkEvidenceError, match="insufficient_samples:baseline:reasoning:0"):
        build_selection_payload(rows, baseline_variant_id="baseline", workload_budgets=BUDGETS)

    with pytest.raises(BenchmarkEvidenceError, match="unknown_workload"):
        build_selection_payload(
            [sample("baseline", "unknown", 100.0, 0.9)],
            baseline_variant_id="baseline",
            workload_budgets=BUDGETS,
        )
