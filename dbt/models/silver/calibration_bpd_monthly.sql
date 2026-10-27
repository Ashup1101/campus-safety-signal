-- Year-to-date figures from BPD's monthly statistics slides (Board of Public Safety packets).
-- A period that appears in more than one packet keeps one value; `conflicting` flags disagreement.
select
    metric,
    period_year,
    period_month,
    stat_year,
    max(value) as value,
    count(distinct value) > 1 as conflicting,
    count(*) as reports,
    max(source_ref) as source_ref
from {{ ref('stg_calibration__bpd_metrics') }}
group by metric, period_year, period_month, stat_year
