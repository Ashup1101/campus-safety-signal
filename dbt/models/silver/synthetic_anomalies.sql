-- The anomalies planted in each synthetic patch: the labels `patterns score` measures the
-- detector against.
select * from {{ ref('stg_synthetic_anomalies') }}
