"""
Build the stats database the eval's SQL tools read, from the frozen snapshot only:

    python -m eval.build_db --database-url postgresql://postgres@localhost:5432/gaffer_eval

Runs the production ETL (pipeline/etl_v2: snapshot, gameweek stats, past-season
backfill) with its FPL fetches answered from the snapshot, so the database always
matches the API data the live tools replay. Also seeds last season's clubs (which the
FPL API can't provide) and creates a read-only role like production's gaffer_readonly.

The target database is dropped and rebuilt — point this at a throwaway database only.
"""

import argparse
import asyncio
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from eval.replay import FplReplay
from eval.snapshot import DEFAULT_SNAPSHOT, Snapshot
from pipeline import etl_v2

_SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
READONLY_ROLE = "gaffer_eval_readonly"
READONLY_PASSWORD = "gaffer_eval_readonly"  # throwaway local database only


async def _seed_previous_season(conn: asyncpg.Connection, snap: Snapshot) -> None:
    if not snap.previous_season_teams:
        return
    start = int(snap.season_label()[:4]) - 1
    season_id = await conn.fetchval(
        """
        INSERT INTO seasons (label, start_year, is_current) VALUES ($1, $2, FALSE)
        ON CONFLICT (label) DO UPDATE SET start_year = EXCLUDED.start_year RETURNING id
        """,
        f"{start}/{str(start + 1)[2:]}",
        start,
    )
    # FPL numbers clubs alphabetically each season.
    for fpl_id, team in enumerate(sorted(snap.previous_season_teams, key=lambda t: t["name"])):
        await conn.execute(
            "INSERT INTO teams (season_id, fpl_id, name, short_name) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (season_id, fpl_id) DO NOTHING",
            season_id,
            fpl_id + 1,
            team["name"],
            team["short_name"],
        )


async def _create_readonly_role(conn: asyncpg.Connection) -> None:
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", READONLY_ROLE)
    if not exists:
        await conn.execute(f"CREATE ROLE {READONLY_ROLE} LOGIN PASSWORD '{READONLY_PASSWORD}'")
    await conn.execute(f"GRANT USAGE ON SCHEMA public TO {READONLY_ROLE}")
    await conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READONLY_ROLE}")


def readonly_url(database_url: str) -> str:
    """The same database, connected as the read-only role (what the app's tools use)."""
    parts = urlsplit(database_url)
    host = parts.hostname or "localhost"
    netloc = f"{READONLY_ROLE}:{READONLY_PASSWORD}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


async def build(database_url: str, snap: Snapshot) -> None:
    replay = FplReplay(snap)

    async def _frozen_get(_client, path: str) -> dict:
        body = replay.lookup(path)
        if body is None:
            raise RuntimeError(f"snapshot has no response for {path}")
        return body  # type: ignore[return-value]

    etl_v2._fpl_get = _frozen_get  # the ETL's only FPL entry point
    etl_v2._cw = None  # no CloudWatch heartbeat from an eval build

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        # schema.sql creates pg_trgm after the index that needs it; production only works
        # because the extension already exists there.
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await conn.execute(_SCHEMA.read_text())
        await etl_v2.run_snapshot(conn)
    finally:
        await conn.close()

    pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    try:
        await etl_v2.run_gw_update(pool)
        await etl_v2.run_backfill(pool)
        async with pool.acquire() as conn:
            await _seed_previous_season(conn, snap)
            # The snapshot refresh ran before gameweek stats existed.
            await conn.execute("REFRESH MATERIALIZED VIEW player_xpts")
            await _create_readonly_role(conn)
            counts = await conn.fetchrow(
                "SELECT (SELECT count(*) FROM players) AS players, "
                "(SELECT count(*) FROM gw_player_stats) AS gw_stats, "
                "(SELECT count(*) FROM player_xpts) AS xpts, "
                "(SELECT count(*) FROM seasons) AS seasons"
            )
    finally:
        await pool.close()
    print(f"built {snap.name}: {dict(counts)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the eval's frozen stats database.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    args = parser.parse_args()
    asyncio.run(build(args.database_url, Snapshot.load(args.snapshot)))


if __name__ == "__main__":
    main()
