# Saved plans

`drafts.json` contains authored transfer-planning hypotheses from the local decision
room. These are editable plans, not immutable forecasts, journal recommendations or
proof of changes submitted to FPL.

Each draft keeps the analysis-run id used for its most recent evaluation. The frontend
marks the draft stale when the current projections no longer match that run and offers
an explicit recalculation before it is saved again.
