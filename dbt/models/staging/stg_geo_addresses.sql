select * from {{ source('lake_staging', 'geo_addresses') }}
