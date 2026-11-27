-- Delete account (v13, AUTH_MODE=supabase): Supabase Auth users still to delete after the account
-- rows are gone (the Auth admin API was unreachable). Only the Auth user id; removed once done.
create table auth_deletions (
    user_id text collate "C" primary key,
    attempts integer not null default 0,
    last_error_kind text collate "C"
);
alter table auth_deletions enable row level security;
