-- IU crime log entries vs BPD calls for service per month, police reporting zone and category,
-- for the console. Only categories both sources name are compared (the mapping below); calls are
-- not crimes, so the two counts measure different things. Sensitive offenses never count: IU's
-- are filtered by is_sensitive and no BPD sensitive nature (sex offense, domestic) is mapped.
-- IU entries count where their location was placed in a zone; zones with no placed IU entry are
-- left out (nothing to compare), and only months both sources cover are kept.
with mapping (category, priority, iu_pattern, bpd_pattern) as (
    values
        ('weapons', 1, 'WEAPON|FIREARM|HANDGUN|\bGUN\b', '^WEAPONS '),
        ('assault', 2, 'ASSAULT|BATTERY', '^(ASSAULT|FIGHT) '),
        ('burglary', 3, 'BURGLARY|UNLAWFUL ENTRY', '^BURGLARY '),
        ('theft', 4, 'THEFT|LARCENY|SHOPLIFT', '^(VEH )?THEFT '),
        ('vandalism', 5, 'VANDAL|MISCHIEF|GRAFFITI', '^VANDALISM '),
        ('alcohol', 6, 'ALCOHOL|LIQUOR|INTOXICAT|DRUNK|CONSUMPTION', '^INTOXICATED'),
        ('drugs', 7, 'DRUG|NARCOTIC|MARIJUANA|PARAPHERNALIA|METHAMPHETAMINE|COCAINE', '^DRUGS '),
        ('harassment', 8, 'HARASSMENT|INTIMIDATION', '^HARASSMENT '),
        ('disturbance', 9, 'DISORDERLY|DISTURB', '^DISTURBANCE '),
        ('trespass', 10, 'TRESPASS', '^TRESPASS ')
),

iu as (
    select
        i.incident_id,
        date_trunc('month', i.occurred_from)::date as month,
        p.zonecode,
        m.category
    from {{ ref('incidents') }} as i
    inner join {{ ref('geo_placements') }} as p on p.location_text = i.location_text
    inner join mapping as m on regexp_matches(upper(i.incident_type), m.iu_pattern)
    where
        i.source = 'official'
        and not i.is_sensitive
        and i.occurred_from is not null
        and p.zonecode is not null
    qualify row_number() over (partition by i.incident_id order by m.priority) = 1
),

bpd as (
    select
        date_trunc('month', c.called_at)::date as month,
        c.district as zonecode,
        m.category
    from {{ ref('bpd_calls_for_service') }} as c
    inner join mapping as m on regexp_matches(upper(c.nature), m.bpd_pattern)
    where c.called_at is not null and c.district is not null
),

months as (
    select
        greatest(
            (select min(date_trunc('month', called_at)) from {{ ref('bpd_calls_for_service') }}),
            (select min(date_trunc('month', date_reported)) from {{ ref('incidents') }}
                where source = 'official')
        )::date as first_month,
        least(
            (select max(date_trunc('month', called_at)) from {{ ref('bpd_calls_for_service') }}),
            (select max(date_trunc('month', date_reported)) from {{ ref('incidents') }}
                where source = 'official')
        )::date as last_month
),

iu_counts as (
    select month, zonecode, category, count(*) as iu_count
    from iu
    group by all
),

bpd_counts as (
    select month, zonecode, category, count(*) as bpd_count
    from bpd
    where zonecode in (select zonecode from iu)
    group by all
)

select
    coalesce(i.month, b.month) as month,
    coalesce(i.zonecode, b.zonecode) as zonecode,
    coalesce(i.category, b.category) as category,
    coalesce(i.iu_count, 0) as iu_count,
    coalesce(b.bpd_count, 0) as bpd_count
from iu_counts as i
full outer join bpd_counts as b using (month, zonecode, category)
cross join months
where coalesce(i.month, b.month) between months.first_month and months.last_month
order by month, zonecode, category
