# Optimization Safety Envelope

Independent GlacierEQ portfolio implementation aligned to **Fireworks AI** operating themes.

> **Not affiliated.** This repository is not affiliated with, endorsed by, employed by, or deployed at Fireworks AI. No proprietary access, production deployment, customer impact, or company partnership is claimed.

## Purpose

Make serving optimization **behaviorally bounded**. Kernel fusion, quantization, batching, or other latency work is useful only when the workload classes that matter do not drift beyond their declared quality and error budgets.

## Implemented mechanism

`OptimizationSafetyEnvelope` evaluates candidate serving variants against a workload-specific contract:

- maximum quality drop per workload class;
- maximum error-rate increase per workload class;
- minimum latency improvement required to justify the optimization;
- complete evidence coverage across every declared workload.

In **selection mode**, unsafe variants are rejected with reason codes and the fastest safe candidate is selected for canary. In **canary mode**, observed drift is re-evaluated against the same envelope. A canary that crosses a behavioral budget produces `ROLLBACK`; one that remains inside the envelope produces `PROMOTE_CANARY`.

The decision surface is deterministic, rejects duplicate variants and incomplete workload evidence, and emits a SHA-256 receipt.

## Raw benchmark evidence adapter

`benchmark_evidence_adapter.build_selection_payload()` removes a trust boundary that previously sat immediately upstream of the envelope. Instead of accepting caller-authored quality/error deltas, it consumes raw benchmark observations containing variant, workload, latency, quality score, and error outcome.

The adapter:

- requires baseline and candidate coverage for every declared workload;
- enforces a minimum sample count per variant/workload;
- computes mean latency, quality, and error rate from the observations;
- derives each candidate's quality/error deltas against the matching baseline workload;
- refuses unknown workloads, malformed/non-finite metrics, and incomplete evidence;
- emits the normalized payload already consumed by `OptimizationSafetyEnvelope`.

This means a canary decision can now begin at raw benchmark samples rather than at pre-normalized claims about those samples.

## Run

```bash
python -m pytest -q
python scripts/operate.py
```

Build and install:

```bash
python -m pip install build
python -m build
python -m pip install dist/*.whl
optimization-safety-envelope
```

Use measured data:

```bash
optimization-safety-envelope --input optimization-observations.json
```

## Proof surface

- `src/optimization_safety_envelope.py` — selection/canary/rollback engine
- `src/benchmark_evidence_adapter.py` — raw benchmark aggregation and delta derivation
- `src/optimization_safety_cli.py` — installable execution surface
- `tests/test_optimization_safety_envelope.py` — cross-workload safety, canary, rollback, duplicate and missing-evidence tests
- `tests/test_benchmark_evidence_adapter.py` — sample coverage, derived-delta, and unsafe-regression proof
- `tests/test_adversarial.py` — fail-closed adversarial coverage
- `.github/workflows/tests.yml` — tests + cold-start + wheel build/install + installed CLI
- `machine/` — existing Helix target, proof, authority, and promotion surfaces remain preserved

## Current boundary

The engine can now derive its decision inputs from raw supplied benchmark samples; it does not yet launch a benchmark against a serving runtime or observe a live canary stream itself. It claims no Fireworks AI infrastructure access or measured production behavior. The next depth step is a permitted runtime adapter that executes/collects benchmark or canary observations and hands those raw observations into the now-verified evidence adapter.
