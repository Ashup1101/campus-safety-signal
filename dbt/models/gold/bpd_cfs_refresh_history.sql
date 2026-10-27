-- Each pull's view of the portal's last refresh; the gaps between distinct refresh times are
-- the observed refresh cadence.
with refreshes as (
    select distinct rows_updated_at as portal_refreshed_at
    from {{ ref('stg_bpd__metadata') }}
    where rows_updated_at is not null
)

select
    portal_refreshed_at,
    datediff('hour', lag(portal_refreshed_at) over (order by portal_refreshed_at), portal_refreshed_at)
        as hours_since_previous_refresh
from refreshes
order by portal_refreshed_at
