-- BPD calls for service per week (Monday start) and police zone, next to the same week 52 weeks
-- earlier, for the console's weekly trends. Counts only; calls are not crimes. Sensitive call
-- natures never count (the IU log's sensitive pattern, plus mental health and runaway calls).
-- The newest week is left out because it may be partial; 26 full weeks are kept.
with calls as (
    select date_trunc('week', called_at)::date as week, district as zonecode
    from {{ ref('bpd_calls_for_service') }}
    where
        called_at is not null
        and district is not null
        and not regexp_matches(
            upper(coalesce(nature, '')),
            'RAPE|\bSEX|SODOMY|FONDLING|INCEST|VOYEUR|INTIMATE IMAGE|NUDITY|INDECENT|EXPOSURE'
            || '|STALK|DOMESTIC|DATING VIOLENCE|STRANGULATION|INVASION OF PRIVACY|PROTECTIVE ORDER'
            || '|CHILD|PEEPING|PROSTITUTION|SUICIDE|MISSING PERSON|MENTAL|RUNAWAY'
        )
),

weekly as (
    select week, zonecode, count(*) as calls
    from calls
    group by all
),

newest as (
    select max(week) as week from weekly
)

select
    w.week,
    w.zonecode,
    w.calls,
    coalesce(p.calls, 0) as calls_last_year
from weekly as w
cross join newest
left join weekly as p
    on p.zonecode = w.zonecode and p.week = (w.week - interval 52 week)::date
where w.week < newest.week and w.week >= (newest.week - interval 26 week)::date
order by w.zonecode, w.week
