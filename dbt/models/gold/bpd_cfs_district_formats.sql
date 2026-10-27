-- District code shapes (letters as A, digits as 9) and how many distinct codes share each.
select
    regexp_replace(regexp_replace(coalesce(district, '<null>'), '[0-9]', '9', 'g'), '[A-Za-z]', 'A', 'g')
        as pattern,
    count(*) as rows,
    count(distinct district) as districts
from {{ ref('stg_bpd__latest_calls') }}
group by 1
order by rows desc, pattern
