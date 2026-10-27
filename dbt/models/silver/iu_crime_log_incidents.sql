-- Current state per case number + offense: the latest observation's values, plus when the
-- incident was first and last listed.
with observations as (
    select * from {{ ref('stg_iu_crime_log__observations') }}
),

seen as (
    select
        case_number,
        offense,
        min(observed_at) as first_seen,
        max(observed_at) as last_seen,
        count(*) as sightings
    from observations
    group by case_number, offense
),

latest as (
    select *
    from observations
    qualify row_number() over (
        partition by case_number, offense order by observed_at desc, run_id desc
    ) = 1
)

select
    latest.case_number,
    latest.offense,
    latest.offense_raw,
    latest.offense_count,
    latest.date_reported,
    latest.occurred_from,
    latest.occurred_to,
    latest.location,
    latest.location_type,
    latest.geocodable,
    latest.disposition,
    latest.severity,
    latest.sensitive,
    latest.source_ref,
    latest.run_id,
    latest.ingested_at,
    seen.first_seen,
    seen.last_seen,
    seen.sightings
from latest
inner join seen
    on latest.case_number = seen.case_number and latest.offense = seen.offense
