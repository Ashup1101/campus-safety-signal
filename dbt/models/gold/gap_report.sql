-- One row per registered gap: what real data covers the span, what synthetic data patches it,
-- and what the Clery totals say the span should hold. Counts and dates only.
with register as (select * from {{ ref('stg_gap_register') }}),

real_rows as (
    select
        r.gap_id,
        count(i.incident_id) as real_incidents
    from register as r
    left join {{ ref('incidents') }} as i
        on i.source != 'synthetic'
        and i.date_reported between coalesce(r."start", date '1900-01-01')
        and coalesce(r."end", date '2100-01-01')
    group by r.gap_id
),

covered as (
    select
        r.gap_id,
        -- greatest/least skip nulls, so an unmatched join must count as zero explicitly
        coalesce(sum(case when c.range_start is null then 0 else
            date_diff('day', greatest(c.range_start, r."start"), least(c.range_end, r."end")) + 1
        end), 0) as real_days_covered
    from register as r
    left join {{ ref('iu_crime_log_coverage') }} as c
        on c.dataset = 'all' and c.kind = 'covered'
        and r.source = 'iu_crime_log' and r."start" is not null
        and c.range_end >= r."start" and c.range_start <= r."end"
    group by r.gap_id
),

synthetic as (
    select
        gap_id,
        count(*) as synthetic_rows,
        count(distinct seed) as synthetic_seeds,
        count(distinct anomaly_id) as planted_anomalies
    from {{ ref('synthetic_incidents') }}
    group by gap_id
),

clery as (
    select
        r.gap_id,
        sum(c.count) as clery_total
    from register as r
    join {{ ref('calibration_clery') }} as c
        on c.location = 'On Campus'
        and r."start" is not null
        and c.calendar_year between year(r."start") and year(r."end")
    group by r.gap_id
)

select
    r.gap_id,
    r.source,
    r."start" as span_start,
    r."end" as span_end,
    case when r."start" is null then null
        else date_diff('day', r."start", r."end") + 1 end as span_days,
    r.fields,
    coalesce(cv.real_days_covered, 0) as real_days_covered,
    coalesce(rr.real_incidents, 0) as real_incidents,
    coalesce(s.synthetic_rows, 0) as synthetic_rows,
    coalesce(s.synthetic_seeds, 0) as synthetic_seeds,
    coalesce(s.planted_anomalies, 0) as planted_anomalies,
    cl.clery_total,
    r.closing_source
from register as r
left join real_rows as rr on rr.gap_id = r.gap_id
left join covered as cv on cv.gap_id = r.gap_id
left join synthetic as s on s.gap_id = r.gap_id
left join clery as cl on cl.gap_id = r.gap_id
order by r.gap_id
