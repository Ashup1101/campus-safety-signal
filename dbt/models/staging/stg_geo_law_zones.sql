select * from {{ source('lake_staging', 'geo_law_zones') }}
