-- Calls from the newest complete pull: the audit describes the dataset as published now.
with latest as (
    select pull_id
    from {{ ref('stg_bpd__calls') }}
    group by pull_id
    order by max(ingested_at) desc
    limit 1
)

select calls.*
from {{ ref('stg_bpd__calls') }} as calls
inner join latest on calls.pull_id = latest.pull_id
