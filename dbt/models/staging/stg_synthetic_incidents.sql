select * from {{ source('lake_staging', 'synthetic_incidents') }}
