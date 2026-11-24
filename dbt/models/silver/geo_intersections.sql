-- Named intersections (city GIS), campus and downtown, newest copy.
select * from {{ ref('stg_geo_intersections') }}
