-- One-row data audit of the newest pull: size, date range, gaps, nulls, duplicates, freshness.
with calls as (
    select * from {{ ref('stg_bpd__latest_calls') }}
),

repeats as (
    -- Same minute, nature, and district under different case numbers: possible double entries.
    select count(distinct case_number) - 1 as extra
    from calls
    where called_at is not null
    group by date_trunc('minute', called_at), nature, district
    having count(distinct case_number) > 1
),

summary as (
    select
        max(pull_id) as pull_id,
        max(ingested_at) as pulled_at,
        count(*) as rows,
        count(distinct case_number) as case_numbers,
        count(*) filter (where case_number is null) as null_case_numbers,
        count(*) filter (where called_at is null) as unparsed_call_times,
        count(*) filter (where nature is null) as null_natures,
        count(*) filter (where district is null) as null_districts,
        count(*) filter (where report is null) as null_reports,
        count(distinct nature) as natures,
        count(distinct district) as districts,
        min(called_at) as first_call,
        max(called_at) as last_call,
        count(distinct called_at::date) as days_with_calls,
        datediff('day', min(called_at)::date, max(called_at)::date) + 1 as days_in_range
    from calls
)

select
    summary.*,
    rows - case_numbers - null_case_numbers as duplicate_case_rows,
    (select coalesce(sum(extra), 0) from repeats) as same_minute_nature_district_rows,
    days_in_range - days_with_calls as missing_days,
    (
        select max(rows_updated_at)
        from {{ ref('stg_bpd__metadata') }} as meta
        where meta.pull_id = summary.pull_id
    ) as portal_refreshed_at
from summary
