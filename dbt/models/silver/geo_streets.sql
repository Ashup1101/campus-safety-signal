-- Road centerlines (City of Bloomington GIS), campus and downtown, newest copy.
select * from {{ ref('stg_geo_streets') }}
