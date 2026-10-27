-- One row per call: the values from the newest pull that listed it.
select *
from {{ ref('stg_bpd__calls') }}
where case_number is not null
qualify row_number() over (partition by case_number order by observed_at desc, run_id desc) = 1
