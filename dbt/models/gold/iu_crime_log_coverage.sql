-- Which reporting dates the crime log history covers, per dataset and overall ('all'): every
-- parsed snapshot covers its own date window (60 days for today's page, one day for a legacy
-- PDF). Overlapping or adjacent windows merge into one covered range; the holes between ranges
-- are gaps.
with windows as (
    select dataset, window_start, window_end
    from {{ ref('stg_iu_crime_log__runs') }}
    where parse_error is null and window_start is not null
    union all
    select 'all', window_start, window_end
    from {{ ref('stg_iu_crime_log__runs') }}
    where parse_error is null and window_start is not null
),

flagged as (
    select
        *,
        max(window_end) over (
            partition by dataset order by window_start, window_end
            rows between unbounded preceding and 1 preceding
        ) as reach
    from windows
),

islands as (
    select
        *,
        sum(case when reach is null or window_start > reach + 1 then 1 else 0 end) over (
            partition by dataset order by window_start, window_end
        ) as island
    from flagged
),

covered as (
    select dataset, min(window_start) as range_start, max(window_end) as range_end
    from islands
    group by dataset, island
),

gaps as (
    select
        dataset,
        range_end + 1 as range_start,
        lead(range_start) over (partition by dataset order by range_start) - 1 as range_end
    from covered
)

select dataset, 'covered' as kind, range_start, range_end, range_end - range_start + 1 as days
from covered
union all
select dataset, 'gap', range_start, range_end, range_end - range_start + 1
from gaps
where range_end is not null
