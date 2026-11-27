-- Push notifications (v14): each phone's Expo push token (personal data: never logged or shown),
-- and a log of pushes by key and ticket (never the message text).
create table devices (
    token text collate "C" primary key,
    account_id text collate "C" not null references accounts (id),
    platform text collate "C" not null check (platform in ('ios')),
    created_at text collate "C" not null
);
create table push_log (
    key text collate "C" not null,
    token text collate "C" not null,
    account_id text collate "C" not null references accounts (id),
    ticket_id text collate "C",
    status text collate "C" not null check (status in ('sent', 'ok', 'error')),
    error_kind text collate "C",
    created_at text collate "C" not null,
    primary key (key, token)
);
alter table devices enable row level security;
alter table push_log enable row level security;
