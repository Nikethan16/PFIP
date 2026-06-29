"""ORM models mirroring the schemas in ``docs/CONTRACTS.md``.

Importing this package imports every model so Alembic autogenerate sees them.
"""

from pfip.models.backtest import BacktestRunRow  # noqa: F401
from pfip.models.calibration import CalibrationRow  # noqa: F401
from pfip.models.calibration_reports import (  # noqa: F401
    CalibrationReportRow,
    ModelEventRow,
    RegimeTransitionRow,
)
from pfip.models.event import EventRow  # noqa: F401
from pfip.models.features import FeatureRow  # noqa: F401
from pfip.models.fundamentals import FundamentalRow  # noqa: F401
from pfip.models.holdings import HoldingRow  # noqa: F401
from pfip.models.journal import JournalRow  # noqa: F401
from pfip.models.news import NewsRow  # noqa: F401
from pfip.models.ohlcv import OHLCVRow  # noqa: F401
from pfip.models.portfolio_tx import PortfolioTxRow  # noqa: F401
from pfip.models.regime import RegimeRow  # noqa: F401
from pfip.models.self_custody import SelfCustodyAddressRow  # noqa: F401
from pfip.models.shadow import ShadowHoldingRow, ShadowPortfolioTxRow  # noqa: F401
from pfip.models.signals import SignalRow  # noqa: F401
from pfip.models.user_settings import UserSettingsRow  # noqa: F401
from pfip.models.watchlist import WatchlistRow  # noqa: F401
