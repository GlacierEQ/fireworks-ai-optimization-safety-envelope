from __future__ import annotations

import argparse
import json
from pathlib import Path

from optimization_safety_envelope import Decision, OptimizationSafetyEnvelope, OptimizationSafetyEnvelopeRequest


def default_payload() -> dict:
    budgets = {
        "chat": {"max_quality_drop": 0.02, "max_error_rate_increase": 0.005},
        "code": {"max_quality_drop": 0.01, "max_error_rate_increase": 0.003},
    }
    return {
        "workload_budgets": budgets,
        "min_latency_improvement_pct": 5.0,
        "variants": [
            {
                "variant_id": "fused-kernel",
                "baseline_latency_ms": 100.0,
                "latency_ms": 72.0,
                "workload_deltas": {
                    "chat": {"quality_delta": -0.006, "error_rate_delta": 0.001},
                    "code": {"quality_delta": -0.004, "error_rate_delta": 0.001},
                },
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate serving optimizations against behavioral drift budgets")
    parser.add_argument("--input", type=Path, help="JSON payload; defaults to built-in demo")
    parser.add_argument("--subject", default="optimization-demo")
    parser.add_argument("--budget", type=float, default=1.0)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text()) if args.input else default_payload()
    receipt = OptimizationSafetyEnvelope().evaluate(OptimizationSafetyEnvelopeRequest(args.subject, payload, args.budget))
    print(json.dumps(receipt.as_dict(), sort_keys=True, indent=2))
    return 0 if receipt.decision is Decision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
