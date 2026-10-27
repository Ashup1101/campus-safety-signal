-- Which source datasets back each conformed incident: one row per incident and dataset (live
-- capture, archive backfill), with when that dataset first and last listed it.
with observations as (
    select * from {{ ref('stg_iu_crime_log__observations') }}
)

select
    md5('iu_crime_log|' || case_number || '|' || offense) as incident_id,
    'official' as source,
    dataset,
    max_by(source_ref, observed_at) as source_ref,
    case_number || '|' || offense as source_record_id,
    max_by(run_id, observed_at) as run_id,
    max(ingested_at) as ingested_at,
    min(observed_at) as first_seen,
    max(observed_at) as last_seen
from observations
group by case_number, offense, dataset
