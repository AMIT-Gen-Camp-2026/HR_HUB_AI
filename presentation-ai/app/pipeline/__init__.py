"""Every pipeline stage lives in its own module here. Read run.py first — it is the
orchestrator and the map of the whole feature. Each stage module is independently
unit-testable and (per docs/DECISIONS.md §7) clearly marked as either deterministic
(no AI) or AI-backed, so you always know what a stage costs and whether it needs a
provider at all."""
