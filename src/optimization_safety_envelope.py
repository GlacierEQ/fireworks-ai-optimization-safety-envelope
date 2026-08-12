"""Optimization Safety Envelope.

Evaluates serving optimizations against workload-specific behavioral drift
budgets before allowing a canary, and deterministically orders rollback when
observed canary drift exceeds the declared envelope.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _digest(obj: object) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class OptimizationSafetyEnvelopeRequest:
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget: float = 1.0
    grant_id: str | None = None
    not_after: float | None = None


@dataclass(frozen=True)
class OptimizationSafetyEnvelopeReceipt:
    decision: Decision
    reasons: tuple[str, ...]
    digest: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "digest": self.digest,
            "metrics": self.metrics,
        }


class EnvelopeError(ValueError):
    pass


class OptimizationSafetyEnvelope:
    MIN_BUDGET = 0.0
    DEFAULT_MIN_LATENCY_GAIN_PCT = 5.0

    @staticmethod
    def _number(value: Any, label: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EnvelopeError(f"{label}_invalid")
        number = float(value)
        if not math.isfinite(number):
            raise EnvelopeError(f"{label}_not_finite")
        if minimum is not None and number < minimum:
            raise EnvelopeError(f"{label}_below_minimum")
        if maximum is not None and number > maximum:
            raise EnvelopeError(f"{label}_above_maximum")
        return number

    @classmethod
    def _budgets(cls, raw: Any) -> dict[str, dict[str, float]]:
        if not isinstance(raw, dict) or not raw:
            raise EnvelopeError("workload_budgets_missing")
        out: dict[str, dict[str, float]] = {}
        for workload, value in sorted(raw.items()):
            name = str(workload).strip()
            if not name or not isinstance(value, dict):
                raise EnvelopeError("workload_budget_invalid")
            out[name] = {
                "max_quality_drop": cls._number(value.get("max_quality_drop"), f"{name}_max_quality_drop", minimum=0, maximum=1),
                "max_error_rate_increase": cls._number(value.get("max_error_rate_increase"), f"{name}_max_error_rate_increase", minimum=0, maximum=1),
            }
        return out

    @classmethod
    def _variant(cls, raw: Any, index: int, budgets: dict[str, dict[str, float]]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise EnvelopeError(f"variant_{index}_not_object")
        variant_id = str(raw.get("variant_id", "")).strip()
        if not variant_id:
            raise EnvelopeError(f"variant_{index}_id_missing")
        baseline_latency = cls._number(raw.get("baseline_latency_ms"), f"variant_{index}_baseline_latency_ms", minimum=0.001)
        latency = cls._number(raw.get("latency_ms"), f"variant_{index}_latency_ms", minimum=0.001)
        deltas = raw.get("workload_deltas")
        if not isinstance(deltas, dict):
            raise EnvelopeError(f"variant_{index}_workload_deltas_missing")
        normalized: dict[str, dict[str, float]] = {}
        for workload in budgets:
            row = deltas.get(workload)
            if not isinstance(row, dict):
                raise EnvelopeError(f"variant_{variant_id}_missing_workload:{workload}")
            normalized[workload] = {
                "quality_delta": cls._number(row.get("quality_delta"), f"{variant_id}_{workload}_quality_delta", minimum=-1, maximum=1),
                "error_rate_delta": cls._number(row.get("error_rate_delta"), f"{variant_id}_{workload}_error_rate_delta", minimum=-1, maximum=1),
            }
        return {
            "variant_id": variant_id,
            "baseline_latency_ms": baseline_latency,
            "latency_ms": latency,
            "workload_deltas": normalized,
        }

    @staticmethod
    def _violations(variant: dict[str, Any], budgets: dict[str, dict[str, float]]) -> list[str]:
        violations: list[str] = []
        for workload, limits in budgets.items():
            delta = variant["workload_deltas"][workload]
            quality_drop = max(0.0, -delta["quality_delta"])
            error_increase = max(0.0, delta["error_rate_delta"])
            if quality_drop > limits["max_quality_drop"]:
                violations.append(f"quality_budget_exceeded:{workload}")
            if error_increase > limits["max_error_rate_increase"]:
                violations.append(f"error_budget_exceeded:{workload}")
        return violations

    @staticmethod
    def _latency_gain_pct(variant: dict[str, Any]) -> float:
        return 100.0 * (variant["baseline_latency_ms"] - variant["latency_ms"]) / variant["baseline_latency_ms"]

    def evaluate(self, req: OptimizationSafetyEnvelopeRequest) -> OptimizationSafetyEnvelopeReceipt:
        reasons: list[str] = []
        if not str(req.subject_id or "").strip():
            reasons.append("subject_id_missing")
        try:
            budget = self._number(req.budget, "budget", minimum=0)
        except EnvelopeError as exc:
            budget = 0.0
            reasons.append(str(exc))
        if budget <= self.MIN_BUDGET:
            reasons.append("budget_non_positive")

        payload = req.payload if isinstance(req.payload, dict) else {}
        if not isinstance(req.payload, dict):
            reasons.append("payload_not_object")

        action = "NONE"
        selected: dict[str, Any] | None = None
        rejected: list[dict[str, Any]] = []
        safe: list[dict[str, Any]] = []
        try:
            budgets = self._budgets(payload.get("workload_budgets"))
            min_gain = self._number(
                payload.get("min_latency_improvement_pct", self.DEFAULT_MIN_LATENCY_GAIN_PCT),
                "min_latency_improvement_pct",
                minimum=0,
                maximum=100,
            )
            mode = str(payload.get("mode", "select")).strip().lower()
            if mode == "select":
                variants = payload.get("variants")
                if not isinstance(variants, list) or not variants:
                    raise EnvelopeError("variants_missing")
                seen: set[str] = set()
                for index, raw in enumerate(variants):
                    variant = self._variant(raw, index, budgets)
                    if variant["variant_id"] in seen:
                        raise EnvelopeError(f"duplicate_variant_id:{variant['variant_id']}")
                    seen.add(variant["variant_id"])
                    violations = self._violations(variant, budgets)
                    gain = self._latency_gain_pct(variant)
                    if gain < min_gain:
                        violations.append("latency_gain_below_minimum")
                    row = {**variant, "latency_gain_pct": round(gain, 9)}
                    if violations:
                        rejected.append({"variant_id": variant["variant_id"], "violations": violations})
                    else:
                        safe.append(row)
                if not safe:
                    raise EnvelopeError("no_variant_inside_safety_envelope")
                safe.sort(key=lambda row: (-row["latency_gain_pct"], row["latency_ms"], row["variant_id"]))
                selected = safe[0]
                action = "CANARY"
            elif mode == "canary":
                observed = self._variant(payload.get("observed"), 0, budgets)
                violations = self._violations(observed, budgets)
                gain = self._latency_gain_pct(observed)
                selected = {**observed, "latency_gain_pct": round(gain, 9)}
                if violations or gain < min_gain:
                    action = "ROLLBACK"
                    reasons.append("rollback_required")
                    rejected.append({"variant_id": observed["variant_id"], "violations": violations + (["latency_gain_below_minimum"] if gain < min_gain else [])})
                else:
                    action = "PROMOTE_CANARY"
            else:
                raise EnvelopeError("mode_invalid")
        except EnvelopeError as exc:
            reasons.append(str(exc))

        decision = Decision.REFUSE if reasons else Decision.ALLOW
        metrics: dict[str, Any] = {
            "action": action,
            "selected_variant_id": selected.get("variant_id") if selected else None,
            "selected": selected,
            "safe_variant_count": len(safe),
            "rejected": rejected,
        }
        body = {
            "subject_id": req.subject_id,
            "decision": decision.value,
            "reasons": reasons,
            "metrics": metrics,
        }
        return OptimizationSafetyEnvelopeReceipt(
            decision=decision,
            reasons=tuple(reasons or ["optimization_inside_behavioral_envelope"]),
            digest=_digest(body),
            metrics=metrics,
        )


Mechanism = OptimizationSafetyEnvelope
