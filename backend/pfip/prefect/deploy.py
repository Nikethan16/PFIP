"""Register Prefect deployments for the flows.

Run once (inside the backend container, after the Prefect server is up):
    python -m pfip.prefect.deploy
"""

from __future__ import annotations

import asyncio

from prefect.client.schemas.schedules import CronSchedule

from pfip.prefect.flows.compute_features import compute_features_flow
from pfip.prefect.flows.ingest_btc_daily import ingest_btc_daily


async def main() -> None:
    """Register deployments with a cron schedule."""
    # BTC daily ingest — 00:05 UTC every day.
    await ingest_btc_daily.serve(  # type: ignore[attr-defined]
        name="ingest-btc-daily",
        tags=["ingest", "crypto"],
        schedule=CronSchedule(cron="5 0 * * *", timezone="UTC"),
        parameters={"exchange": "coinbase", "symbol": "BTC/USD", "timeframe": "1d"},
        pause_on_shutdown=False,
    )
    await compute_features_flow.serve(  # type: ignore[attr-defined]
        name="compute-features-btc-daily",
        tags=["features", "crypto"],
        schedule=CronSchedule(cron="15 0 * * *", timezone="UTC"),
        parameters={"symbol": "BTC/USD", "source": "coinbase", "timeframe": "1d"},
        pause_on_shutdown=False,
    )


if __name__ == "__main__":
    asyncio.run(main())
