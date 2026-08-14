"""Convert raw serving benchmark observations into safety-envelope evidence."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable


class BenchmarkEvidenceError(ValueError):
    pass


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkEvidenceError(f"{label}_invalid")
    number = float(value)
    if not math.isfinite(number):
        raise BenchmarkEvidenceError(f"{label}_not_finite")
    if minimum is not None and number < minimum:
        raise BenchmarkEvidenceError(f"{label}_below_minimum")
    return number


def build_selection_payload(
    observations: Iterable[dict[str, Any]],
    *,
    baseline_variant_id: str,
    workload_budgets: dict[str, dict[str, float]],
    min_latency_improvement_pct: float = 5.0,
    min_samples_per_workload: int = 3,
) -> dict[str, Any]:
    """Aggregate benchmark samples into the optimizer's normalized evidence contract.

    Every sample must contain ``variant_id``, ``workload``, ``latency_ms``,
    ``quality_score`` and ``error``. Candidate deltas are derived against the
    baseline mean for the same workload, preventing callers from supplying their
    own convenient deltas while retaining a vendor-neutral benchmark boundary.
    """
    baseline_variant_id = str(baseline_variant_id).strip()
    if not baseline_variant_id:
        raise BenchmarkEvidenceError("baseline_variant_id_missing")
    if not isinstance(min_samples_per_workload, int) or isinstance(min_samples_per_workload, bool):
        raise BenchmarkEvidenceError("min_samples_per_workload_invalid")
    if min_samples_per_workload < 1:
        raise BenchmarkEvidenceError("min_samples_per_workload_below_minimum")
    if not isinstance(workload_budgets, dict) or not workload_budgets:
        raise BenchmarkEvidenceError("workload_budgets_missing")

    grouped: dict[tuple[str, str], list[tuple[float, float, float]]] = defaultdict(list)
    for index, raw in enumerate(observations):
        if not isinstance(raw, dict):
            raise BenchmarkEvidenceError(f"sample_{index}_not_object")
        variant = str(raw.get("variant_id", "")).strip()
        workload = str(raw.get("workload", "")).strip()
        if not variant:
            raise BenchmarkEvidenceError(f"sample_{index}_variant_id_missing")
        if not workload:
            raise BenchmarkEvidenceError(f"sample_{index}_workload_missing")
        if workload not in workload_budgets:
            raise BenchmarkEvidenceError(f"sample_{index}_unknown_workload:{workload}")
        latency = _number(raw.get("latency_ms"), f"sample_{index}_latency_ms", minimum=0.001)
        quality = _number(raw.get("quality_score"), f"sample_{index}_quality_score", minimum=0.0)
        if quality > 1.0:
            raise BenchmarkEvidenceError(f"sample_{index}_quality_score_above_maximum")
        error = raw.get("error")
        if not isinstance(error, bool):
            raise BenchmarkEvidenceError(f"sample_{index}_error_invalid")
        grouped[(variant, workload)].append((latency, quality, 1.0 if error else 0.0))

    workloads = tuple(sorted(workload_budgets))
    variants = sorted({variant for variant, _ in grouped})
    if baseline_variant_id not in variants:
        raise BenchmarkEvidenceError("baseline_variant_missing")
    candidates = [variant for variant in variants if variant != baseline_variant_id]
    if not candidates:
        raise BenchmarkEvidenceError("candidate_variant_missing")

    means: dict[tuple[str, str], tuple[float, float, float]] = {}
    for variant in variants:
        for workload in workloads:
            samples = grouped.get((variant, workload), [])
            if len(samples) < min_samples_per_workload:
                raise BenchmarkEvidenceError(
                    f"insufficient_samples:{variant}:{workload}:{len(samples)}"
                )
            n = float(len(samples))
            means[(variant, workload)] = (
                sum(row[0] for row in samples) / n,
                sum(row[1] for row in samples) / n,
                sum(row[2] for row in samples) / n,
            )

    baseline_latency = sum(means[(baseline_variant_id, w)][0] for w in workloads) / len(workloads)
    normalized: list[dict[str, Any]] = []
    for variant in candidates:
        candidate_latency = sum(means[(variant, w)][0] for w in workloads) / len(workloads)
        deltas: dict[str, dict[str, float]] = {}
        for workload in workloads:
            _, base_quality, base_error = means[(baseline_variant_id, workload)]
            _, candidate_quality, candidate_error = means[(variant, workload)]
            deltas[workload] = {
                "quality_delta": candidate_quality - base_quality,
                "error_rate_delta": candidate_error - base_error,
            }
        normalized.append(
            {
                "variant_id": variant,
                "baseline_latency_ms": baseline_latency,
                "latency_ms": candidate_latency,
                "workload_deltas": deltas,
            }
        )

    return {
        "mode": "select",
        "workload_budgets": workload_budgets,
        "min_latency_improvement_pct": min_latency_improvement_pct,
        "variants": normalized,
        "evidence": {
            "source": "raw_benchmark_samples",
            "baseline_variant_id": baseline_variant_id,
            "sample_count": sum(len(rows) for rows in grouped.values()),
            "min_samples_per_workload": min_samples_per_workload,
        },
    }
