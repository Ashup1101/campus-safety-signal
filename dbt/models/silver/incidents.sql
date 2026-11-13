-- Conformed incidents across sources. The IU crime log is an official source; fields it does
-- not carry (coordinates, zones, injuries, summaries) stay null until later phases fill them.
-- News clusters join with a templated summary (never article text) and a confidence that
-- follows the alerts.md tiers: official 1.0, two outlets 0.8, one outlet 0.5.
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

union all

select
    md5('news|' || cluster_id) as incident_id,
    case when official then 'official' else 'news' end as source,
    source_ref,
    cluster_id as source_record_id,
    run_id,
    ingested_at,
    incident_type,
    cast(null as varchar) as offense_raw,
    severity_tier,
    1 as count,
    cast(first_published_at as date) as date_reported,
    case
        when occurred_date is null then null
        when occurred_time is null then cast(occurred_date as timestamp)
        else cast(occurred_date as timestamp) + cast(occurred_time || ':00' as interval)
    end as occurred_from,
    cast(null as timestamp) as occurred_to,
    case when occurred_time is not null then 'exact' else 'date' end as time_precision,
    location_text,
    location_type,
    cast(null as varchar) as business_name,
    cast(null as double) as lat,
    cast(null as double) as lon,
    case when location_text is null then 'not_geocodable' else 'pending' end as geocode_quality,
    cast(null as varchar) as zone_id,
    cast(null as varchar) as disposition,
    is_sensitive,
    injuries,
    deaths,
    weapon_involved,
    incident_type || ' reported'
        || coalesce(' near ' || location_text, '')
        || ' (' || case when official then 'official notice' else outlets || ' outlet'
        || case when outlets = 1 then '' else 's' end end || ')' as summary,
    cast(case when official then 1.0 when outlets >= 2 then 0.8 else 0.5 end as double)
        as confidence,
    cast(null as varchar) as gap_id,
    cast(null as bigint) as seed
from {{ ref('news_incidents') }}

union all

select
    md5('synthetic|' || gap_id || '|' || seed || '|' || n) as incident_id,
    'synthetic' as source,
    source_ref,
    case_number as source_record_id,
    run_id,
    ingested_at,
    incident_type,
    cast(null as varchar) as offense_raw,
    severity as severity_tier,
    1 as count,
    cast(occurred_at as date) as date_reported,
    occurred_at as occurred_from,
    cast(null as timestamp) as occurred_to,
    'exact' as time_precision,
    location as location_text,
    location_type,
    cast(null as varchar) as business_name,
    cast(null as double) as lat,
    cast(null as double) as lon,
    'pending' as geocode_quality,
    zone_id,
    cast(null as varchar) as disposition,
    false as is_sensitive,
    cast(null as integer) as injuries,
    cast(null as integer) as deaths,
    cast(null as boolean) as weapon_involved,
    cast(null as varchar) as summary,
    -- Synthetic rows are never evidence: they patch gaps for patterns and evaluation only.
    cast(0.0 as double) as confidence,
    gap_id,
    seed
from {{ ref('synthetic_incidents') }}
