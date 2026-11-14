-- BPD calls per reporting zone, for the map: every call has a zone code and no address, so the
-- zone is the finest place a call can be shown. BPD's feed also carries calls in IU, county and
-- Ellettsville zones, so every agency's zones are joined. Zones without calls stay (count 0);
-- call codes with no zone in the layer stay with null geometry so the audit sees them.
with calls as (
    select
        district as zonecode,
        count(*) as calls,
        count(*) filter (
            where called_at >= (select max(called_at) from {{ ref('bpd_calls_for_service') }})
                - interval 365 day
        ) as calls_last_365_days,
        min(called_at) as first_call,
        max(called_at) as last_call
    from {{ ref('bpd_calls_for_service') }}
    where district is not null
    group by district
),

zones as (
    select * from {{ ref('geo_law_zones') }}
)

select
    coalesce(z.zonecode, c.zonecode) as zonecode,
    z.agency_code,
    z.district,
    z.sector,
    z.centroid_lat,
    z.centroid_lon,
    z.geometry is not null as has_geometry,
    coalesce(c.calls, 0) as calls,
    coalesce(c.calls_last_365_days, 0) as calls_last_365_days,
    c.first_call,
    c.last_call
from zones as z
full outer join calls as c on c.zonecode = z.zonecode
