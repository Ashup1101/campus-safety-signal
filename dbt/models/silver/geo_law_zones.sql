-- Police reporting zones (City of Bloomington GIS), newest copy: polygon, centroid, agency.
select * from {{ ref('stg_geo_law_zones') }}
