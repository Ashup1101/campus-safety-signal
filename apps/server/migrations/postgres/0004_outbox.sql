-- Real email (v13, EMAIL_MODE=smtp): each message waits here until the provider accepts it.
-- The body is cleared once sent (the in-app mailbox keeps the reader's copy).
create table outbox (
    key text collate "C" primary key,
    account_id text collate "C" not null references accounts (id),
    kind text collate "C" not null,
    to_address text collate "C" not null,
    subject text collate "C" not null,
    body text collate "C" not null,
    unsubscribe_url text collate "C",
    status text collate "C" not null check (status in ('queued', 'sent', 'failed')),
    attempts integer not null default 0,
    last_error_kind text collate "C",
    created_at text collate "C" not null,
    sent_at text collate "C"
);
alter table outbox enable row level security;
