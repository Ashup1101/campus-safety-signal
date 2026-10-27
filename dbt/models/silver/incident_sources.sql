-- Which source records back each conformed incident (one per record today; several once news
-- reports are matched to official ones).
select
    md5('iu_crime_log|' || case_number || '|' || offense) as incident_id,
    'official' as source,
    source_ref,
    case_number || '|' || offense as source_record_id,
    run_id,
    ingested_at,
    first_seen,
    last_seen
from {{ ref('iu_crime_log_incidents') }}
