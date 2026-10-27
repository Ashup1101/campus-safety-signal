-- IU Bloomington Clery counts per branch, location, category, offense, and calendar year. Each
-- calendar year appears in three survey files; the latest survey's figure wins, and `revised`
-- marks years whose figure changed between surveys.
select
    unitid_p,
    any_value(branch) as branch,
    location,
    category,
    offense,
    calendar_year,
    arg_max(count, survey_year) as count,
    max(survey_year) as survey_year,
    count(distinct count) > 1 as revised,
    arg_max(source_ref, survey_year) as source_ref
from {{ ref('stg_calibration__clery') }}
group by unitid_p, location, category, offense, calendar_year
