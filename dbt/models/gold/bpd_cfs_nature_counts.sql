select nature, count(*) as rows, round(100.0 * count(*) / sum(count(*)) over (), 2) as pct
from {{ ref('stg_bpd__latest_calls') }}
group by nature
order by rows desc, nature
