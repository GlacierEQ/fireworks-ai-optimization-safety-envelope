# DEV_UP_INSTRUCTIONS — implementation record

**Repository:** `GlacierEQ/fireworks-ai-optimization-safety-envelope`  
**Independent company lens:** Fireworks AI  
**Innovation:** Optimization Safety Envelope

## Mission

Increase serving efficiency without allowing latency wins to silently purchase workload-specific behavioral regressions.

## Implemented

The generic scaffold has been replaced by a deterministic optimization safety controller.

`src/optimization_safety_envelope.py` now:

- validates explicit quality/error drift budgets by workload class;
- requires complete workload evidence for every candidate;
- computes latency improvement against each candidate's baseline;
- refuses variants outside any workload budget or below the required latency gain;
- deterministically selects the strongest safe variant for canary;
- re-evaluates observed canary drift and emits `ROLLBACK` or `PROMOTE_CANARY`;
- rejects duplicate ids and malformed/non-finite measurements;
- emits structured SHA-256 receipts.

`src/optimization_safety_cli.py` and `scripts/operate.py` execute the mechanism directly. The project is packaged as a wheel with the `optimization-safety-envelope` console command.

## Verification contract

Behavioral tests cover cross-workload selection, quality-regression rejection, all-unsafe refusal, missing workload evidence, rollback, canary promotion, minimum gain, and duplicate ids. Existing adversarial coverage remains active.

CI must pass native tests, cold-start operation, wheel build/install, and installed CLI execution before Helix may mint source-bound promotion evidence.

## Truth boundary

No Fireworks AI affiliation, proprietary access, production deployment, customer impact, or company partnership is claimed. Current inputs are explicit evaluation observations; a later adapter can bind real permitted benchmark/canary outputs to this contract.
