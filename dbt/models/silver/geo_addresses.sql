-- Address points (city GIS), one row per street address, newest copy.
select * from {{ ref('stg_geo_addresses') }}
