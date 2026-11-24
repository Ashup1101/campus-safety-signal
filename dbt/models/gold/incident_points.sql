-- Placed incidents for maps: real (official) and non-sensitive only, with category, time and
-- precision. No location text, names or free text: coordinates come from public city layers.
select
    i.incident_id,
    i.incident_type,
    i.severity_tier,
    i.date_reported,
    i.occurred_from,
    i.time_precision,
    i.geocode_quality as precision,
    i.lat,
    i.lon,
    p.street_objectid
from {{ ref('incidents') }} as i
left join {{ ref('geo_placements') }} as p on p.location_text = i.location_text
where
    i.source = 'official'
    and not i.is_sensitive
    and i.lat is not null
    and i.geocode_quality in ('segment', 'address', 'block')
