-- Crime log location strings placed on the city's street network (geo.place): precision,
-- coordinates and, for street stretches, the centerline piece. Unplaced strings have no row.
select * from {{ ref('stg_geo_placements') }}
