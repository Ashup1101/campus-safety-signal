select year(called_at) as year, count(*) as rows
from {{ ref('stg_bpd__latest_calls') }}
where called_at is not null
group by 1
order by 1
