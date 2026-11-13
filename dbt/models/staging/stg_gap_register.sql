select * from {{ source('lake_staging', 'gap_register') }}
