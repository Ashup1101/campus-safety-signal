-- Calendar days inside the published range with no calls at all.
with calls as (
    select called_at::date as day from {{ ref('stg_bpd__latest_calls') }} where called_at is not null
),

bounds as (
    select min(day) as first_day, max(day) as last_day from calls
),

calendar as (
    select unnest(generate_series(first_day, last_day, interval 1 day))::date as day
    from bounds
    where first_day is not null
)

select day
from calendar
where day not in (select day from calls)
order by day
