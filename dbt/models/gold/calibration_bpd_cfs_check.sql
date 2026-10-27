-- Calls for service the city reported year to date vs. the rows the open-data feed holds for
-- the same period: a completeness check on the SODA dataset.
with reported as (
    select period_year, period_month, value as reported_calls
    from {{ ref('calibration_bpd_monthly') }}
    where metric = 'calls_for_service_ytd'
),

feed as (
    select
        reported.period_year,
        reported.period_month,
        count(calls.case_number) as feed_calls
    from reported
    left join {{ ref('bpd_calls_for_service') }} as calls
        on calls.called_at >= make_date(reported.period_year, 1, 1)
        and calls.called_at < make_date(reported.period_year, reported.period_month, 1) + interval 1 month
    group by reported.period_year, reported.period_month
)

select
    reported.period_year,
    reported.period_month,
    reported.reported_calls,
    feed.feed_calls,
    feed.feed_calls - reported.reported_calls as difference,
    round(100.0 * (feed.feed_calls - reported.reported_calls) / nullif(reported.reported_calls, 0), 2)
        as pct_difference
from reported
inner join feed using (period_year, period_month)
order by period_year, period_month
