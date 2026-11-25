select * from {{ source('lake_staging', 't1_forecast') }}
