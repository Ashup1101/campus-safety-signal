-- Supabase Auth sign-in (v13): the Auth user id an account signed in with, once known.
alter table accounts add column auth_user_id text collate "C";
create unique index accounts_auth_user on accounts (auth_user_id) where auth_user_id is not null;
