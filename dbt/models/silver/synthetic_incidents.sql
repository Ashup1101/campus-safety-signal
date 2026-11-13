-- Synthetic patches (Phase 4): seeded Poisson rows for registered gaps only. Every row names
-- its gap and seed; planted anomalies are labeled so detectors can be scored against them.
select * from {{ ref('stg_synthetic_incidents') }}
