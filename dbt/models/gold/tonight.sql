-- Tonight's expected level per police zone from the newest imported T1 run (t1 import checked
-- it). method says whether the trained model or the simple rule made it (the honesty switch).
-- Counts of calls for service only; calls are not crimes.
select zonecode, night, "window", expected, level, method, reason, run_id, imported_at
from {{ ref('stg_t1_forecast') }}
