import psycopg


def test_embedded_postgres_answers(pg_url: str) -> None:
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("select 1").fetchone() == (1,)
