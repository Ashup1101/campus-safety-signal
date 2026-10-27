select * from {{ source('lake_staging', 'bpd_cfs_metadata') }}
