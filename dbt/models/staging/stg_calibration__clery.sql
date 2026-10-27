select * from {{ source('lake_staging', 'calibration_clery_rows') }}
