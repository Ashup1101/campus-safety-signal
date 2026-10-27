-- One row when an incident first appears and one per change to a tracked field. A snapshot that
-- re-lists the same values adds nothing, so history is derived from observations, never written.
with compared as (
    select
        *,
        row_number() over w as sighting,
        lag(offense_count) over w as prev_offense_count,
        lag(date_reported) over w as prev_date_reported,
        lag(occurred_from) over w as prev_occurred_from,
        lag(occurred_to) over w as prev_occurred_to,
        lag(location) over w as prev_location,
        lag(disposition) over w as prev_disposition
    from {{ ref('stg_iu_crime_log__observations') }}
    window w as (partition by case_number, offense order by observed_at, run_id)
)

select
    case_number,
    offense,
    dataset,
    source_ref,
    run_id,
    observed_at,
    offense_count,
    date_reported,
    occurred_from,
    occurred_to,
    location,
    disposition
from compared
where sighting = 1
    or offense_count is distinct from prev_offense_count
    or date_reported is distinct from prev_date_reported
    or occurred_from is distinct from prev_occurred_from
    or occurred_to is distinct from prev_occurred_to
    or location is distinct from prev_location
    or disposition is distinct from prev_disposition
