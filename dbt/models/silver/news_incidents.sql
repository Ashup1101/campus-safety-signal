-- One row per cross-outlet cluster: the same incident reported by one or more outlets, with
-- the alerts.md confirmation rule applied (official source, or two independent outlets).
select
    cluster_id,
    incident_type,
    severity as severity_tier,
    sensitive as is_sensitive,
    occurred_date,
    occurred_time,
    location_text,
    location_type,
    injuries,
    deaths,
    weapon_involved,
    iu_related,
    outlets,
    official,
    confirmed,
    item_count,
    first_published_at,
    first_item_id,
    source_ref,
    run_id,
    ingested_at,
    injection_suspected
from {{ ref('stg_news__clusters') }}
