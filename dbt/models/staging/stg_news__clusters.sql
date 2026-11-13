select * from {{ source('lake_staging', 'news_clusters') }}
