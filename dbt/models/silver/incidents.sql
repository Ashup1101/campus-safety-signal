-- Conformed incidents across sources. The IU crime log is an official source; fields it does
-- not carry (coordinates, zones, injuries, summaries) stay null until later phases fill them.
select
    md5('iu_crime_log|' || case_number || '|' || offense) as incident_id,
    'official' as source,
    source_ref,
    case_number || '|' || offense as source_record_id,
    run_id,
    ingested_at,
    offense as incident_type,
    offense_raw,
    severity as severity_tier,
    offense_count as count,
    date_reported,
    occurred_from,
    occurred_to,
    case
        when occurred_from is null and occurred_to is null then 'date'
        when occurred_to is null or occurred_to = occurred_from then 'exact'
        else 'range'
    end as time_precision,
    location as location_text,
    location_type,
    cast(null as varchar) as business_name,
    cast(null as double) as lat,
    cast(null as double) as lon,
    case when geocodable then 'pending' else 'not_geocodable' end as geocode_quality,
    cast(null as varchar) as zone_id,
    disposition,
    sensitive as is_sensitive,
    cast(null as integer) as injuries,
    cast(null as integer) as deaths,
    cast(null as boolean) as weapon_involved,
    cast(null as varchar) as summary,
    -- Rules parsing is exact; LLM-read rows count less until the owner verifies them.
    cast(case extractor when 'rules' then 1.0 when 'llm_verified' then 0.9 else 0.5 end as double)
        as confidence,
    cast(null as varchar) as gap_id,
    cast(null as bigint) as seed
from {{ ref('iu_crime_log_incidents') }}
