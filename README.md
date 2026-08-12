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
- `src/optimization_safety_cli.py` — installable execution surface
- `tests/test_optimization_safety_envelope.py` — cross-workload safety, canary, rollback, duplicate and missing-evidence tests
- `tests/test_adversarial.py` — fail-closed adversarial coverage
- `.github/workflows/tests.yml` — tests + cold-start + wheel build/install + installed CLI
- `machine/` — existing Helix target, proof, authority, and promotion surfaces remain preserved

## Current boundary

The engine operates on supplied evaluation deltas and latency observations. It does not claim Fireworks AI infrastructure access or measured production behavior. The next deployment depth step is a permitted benchmark/canary adapter that converts real evaluation runs into this stable envelope contract.
