from __future__ import annotations

from optimization_safety_envelope import Decision, OptimizationSafetyEnvelope, OptimizationSafetyEnvelopeRequest


BUDGETS = {
    "chat": {"max_quality_drop": 0.02, "max_error_rate_increase": 0.005},
    "code": {"max_quality_drop": 0.01, "max_error_rate_increase": 0.003},
}


def variant(variant_id: str, *, latency: float, chat_q: float = -0.005, chat_e: float = 0.001, code_q: float = -0.004, code_e: float = 0.001) -> dict:
    return {
        "variant_id": variant_id,
        "baseline_latency_ms": 100.0,
        "latency_ms": latency,
        "workload_deltas": {
            "chat": {"quality_delta": chat_q, "error_rate_delta": chat_e},
            "code": {"quality_delta": code_q, "error_rate_delta": code_e},
        },
    }


def evaluate(payload: dict):
    return OptimizationSafetyEnvelope().evaluate(
        OptimizationSafetyEnvelopeRequest(subject_id="serve-1", payload=payload, budget=1.0)
    )


def test_selects_fastest_variant_inside_all_workload_budgets() -> None:
    receipt = evaluate({
        "workload_budgets": BUDGETS,
        "min_latency_improvement_pct": 5.0,
        "variants": [variant("safe-20", latency=80.0), variant("safe-30", latency=70.0)],
    })
    assert receipt.decision is Decision.ALLOW
    assert receipt.metrics["action"] == "CANARY"
    assert receipt.metrics["selected_variant_id"] == "safe-30"
    assert receipt.metrics["selected"]["latency_gain_pct"] == 30.0


def test_rejects_fast_variant_that_regresses_code_quality() -> None:
    receipt = evaluate({
        "workload_budgets": BUDGETS,
        "variants": [
            variant("unsafe", latency=55.0, code_q=-0.04),
            variant("safe", latency=75.0),
        ],
    })
    assert receipt.decision is Decision.ALLOW
    assert receipt.metrics["selected_variant_id"] == "safe"
    rejected = receipt.metrics["rejected"][0]
    assert rejected["variant_id"] == "unsafe"
    assert "quality_budget_exceeded:code" in rejected["violations"]


def test_refuses_when_no_variant_is_safe() -> None:
    receipt = evaluate({
        "workload_budgets": BUDGETS,
        "variants": [variant("bad", latency=60.0, chat_e=0.02, code_e=0.02)],
    })
    assert receipt.decision is Decision.REFUSE
    assert "no_variant_inside_safety_envelope" in receipt.reasons


def test_refuses_variant_without_required_workload_evidence() -> None:
    bad = variant("partial", latency=70.0)
    del bad["workload_deltas"]["code"]
    receipt = evaluate({"workload_budgets": BUDGETS, "variants": [bad]})
    assert receipt.decision is Decision.REFUSE
    assert "variant_partial_missing_workload:code" in receipt.reasons


def test_canary_drift_orders_rollback() -> None:
    receipt = evaluate({
        "mode": "canary",
        "workload_budgets": BUDGETS,
        "observed": variant("int4", latency=60.0, code_q=-0.03),
    })
    assert receipt.decision is Decision.REFUSE
    assert receipt.metrics["action"] == "ROLLBACK"
    assert "rollback_required" in receipt.reasons


def test_canary_inside_envelope_can_promote() -> None:
    receipt = evaluate({
        "mode": "canary",
        "workload_budgets": BUDGETS,
        "observed": variant("kernel-fused", latency=72.0),
    })
    assert receipt.decision is Decision.ALLOW
    assert receipt.metrics["action"] == "PROMOTE_CANARY"


def test_minimum_latency_gain_prevents_quality_neutral_non_improvement() -> None:
    receipt = evaluate({
        "workload_budgets": BUDGETS,
        "min_latency_improvement_pct": 10.0,
        "variants": [variant("tiny", latency=95.0)],
    })
    assert receipt.decision is Decision.REFUSE
    assert receipt.metrics["rejected"][0]["violations"] == ["latency_gain_below_minimum"]


def test_duplicate_variant_ids_fail_closed() -> None:
    receipt = evaluate({
        "workload_budgets": BUDGETS,
        "variants": [variant("same", latency=80.0), variant("same", latency=70.0)],
    })
    assert receipt.decision is Decision.REFUSE
    assert "duplicate_variant_id:same" in receipt.reasons
