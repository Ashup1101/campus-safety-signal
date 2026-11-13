select * from {{ source('lake_staging', 'news_cluster_items') }}
