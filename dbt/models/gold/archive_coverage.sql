-- Wayback archive coverage of the IU crime log per capture year: captures the stored CDX
-- listings name, how many were fetched and parsed, how many were fetched but failed to parse,
-- and how many are not fetched yet (still to backfill, or the fetch failed). Counts only.
with listed as (
    select year(captured_at) as year, count(distinct raw_url) as listed
    from {{ ref('stg_wayback__captures') }}
    group by all
),

runs as (
    select
        year(observed_at) as year,
        count(*) filter (where parse_error is null) as parsed,
        count(*) filter (where parse_error is not null) as failed
    from {{ ref('stg_iu_crime_log__runs') }}
    where dataset = 'iu_crime_log_wayback'
    group by all
)

select
    coalesce(l.year, r.year) as year,
    coalesce(l.listed, 0) as listed,
    coalesce(r.parsed, 0) as parsed,
    coalesce(r.failed, 0) as failed,
    greatest(coalesce(l.listed, 0) - coalesce(r.parsed, 0) - coalesce(r.failed, 0), 0)
        as not_fetched
from listed as l
full outer join runs as r using (year)
order by year
