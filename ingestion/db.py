import os

import psycopg2


def get_connection():
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")

    conn = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )
    conn.autocommit = False
    return conn
