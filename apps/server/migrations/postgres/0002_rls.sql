-- Deny by default: row-level security on every table and no policies, so Supabase's public
-- roles (anon, authenticated) read and write nothing. Only the server's own role (table owner /
-- service role, which bypasses RLS) uses these tables.
alter table accounts enable row level security;
alter table links enable row level security;
alter table zones enable row level security;
alter table alerts enable row level security;
alter table deliveries enable row level security;
alter table mailbox enable row level security;
alter table magic_tokens enable row level security;
alter table invites enable row level security;
alter table ask_usage enable row level security;
alter table notes enable row level security;
alter table note_reports enable row level security;
alter table bans enable row level security;
alter table settings enable row level security;
alter table consents enable row level security;
alter table subscriptions enable row level security;
alter table sub_tokens enable row level security;
alter table survey_answers enable row level security;
alter table device_keys enable row level security;
alter table sent_keys enable row level security;
alter table activity enable row level security;
alter table schema_migrations enable row level security;
