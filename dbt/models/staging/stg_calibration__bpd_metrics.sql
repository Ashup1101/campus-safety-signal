select * from {{ source('lake_staging', 'calibration_bpd_metric_rows') }}
