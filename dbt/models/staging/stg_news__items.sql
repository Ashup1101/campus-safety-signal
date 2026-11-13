select * from {{ source('lake_staging', 'news_items') }}
