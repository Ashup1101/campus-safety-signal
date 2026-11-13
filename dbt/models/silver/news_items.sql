-- Every unique item seen in the news and notice feeds. Text is kept only for relevant items,
-- after name redaction and descriptor stripping (never the article itself).
select * from {{ ref('stg_news__items') }}
