-- One-row audit of the news pipeline: duplicate rate (items per cluster), confirmation rate,
-- how often screening flagged instruction-like text. Counts only.
with items as (select * from {{ ref('news_items') }}),
clusters as (select * from {{ ref('news_incidents') }})

select
    (select count(*) from items) as items,
    (select count(*) from items where relevant) as relevant_items,
    (select count(*) from items where injection_suspected) as injection_suspected_items,
    (select count(*) from clusters) as clusters,
    (select count(*) from clusters where confirmed) as confirmed_clusters,
    (select count(*) from clusters where official) as official_clusters,
    (select count(*) from clusters where is_sensitive) as sensitive_clusters,
    (select coalesce(sum(item_count), 0) from clusters) as clustered_items,
    (select round(coalesce(avg(item_count), 0), 3) from clusters) as items_per_cluster,
    (select min(first_published_at) from clusters) as first_incident,
    (select max(first_published_at) from clusters) as last_incident
