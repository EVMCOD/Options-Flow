from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Options Flow Radar"
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://ofr:ofr@localhost:5432/ofr"

    # Scanner
    SCANNER_UNIVERSE: List[str] = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "AMD", "META"]
    SCAN_INTERVAL_SECONDS: int = 300  # 5 minutes

    # Signal thresholds
    VOLUME_SPIKE_THRESHOLD: float = 2.0   # volume_ratio > this -> MEDIUM alert
    VOLUME_SPIKE_HIGH: float = 4.0        # volume_ratio > this -> HIGH alert
    ZSCORE_THRESHOLD: float = 2.0
    MIN_VOLUME: int = 100                  # ignore ultra-thin strikes
    BASELINE_LOOKBACK_RUNS: int = 20      # how many past runs to use for baseline
    MIN_BASELINE_RUNS_FOR_ALERT: int = 10 # require N historical data points; 10 runs ≈ 50 min at 5-min scans

    # Alert severity thresholds (anomaly score 0–10).
    # Score reference: 5× spike at z=3 → ~4.0; 10× spike at z=5 → 8.0.
    # Raise these to reduce volume; lower to catch weaker signals.
    ALERT_LEVEL_LOW: float = 3.0       # requires genuine anomaly (was 1.5)
    ALERT_LEVEL_MEDIUM: float = 5.0    # requires strong, consistent signal (was 3.0)
    ALERT_LEVEL_HIGH: float = 7.0      # requires very significant flow (was 5.0)
    ALERT_LEVEL_CRITICAL: float = 8.5  # exceptional; must be rare (was 7.0)

    # Priority score gates for elevated levels.
    # priority_score combines anomaly strength + notional value + data quality (0–10).
    # Prevents low-quality / low-notional contracts from reaching HIGH or CRITICAL
    # even when anomaly score alone would qualify.
    MIN_PRIORITY_SCORE_HIGH: float = 5.0      # HIGH alerts must score ≥ 5.0
    MIN_PRIORITY_SCORE_CRITICAL: float = 6.0  # CRITICAL alerts must score ≥ 6.0

    # Signal engine pre-filters (applied before baseline query; cheap local checks)
    # These filter out contracts that are structurally uninteresting or have unreliable data.
    # All filters are configurable per-deployment via environment variables or .env.
    MIN_OPEN_INTEREST: int = 0
    # Minimum open interest. Default 0 because IBKR delayed data often has OI=0.
    # Set to e.g. 50 once you have a reliable OI source to avoid noise from tiny positions.

    MIN_PREMIUM_PROXY: float = 2000.0
    # Minimum notional value proxy in USD: volume × effective_mid × 100.
    # $2,000 = e.g. 200 contracts × $0.10 mid. Filters penny options and thin strikes
    # where a "spike" is just a handful of small trades. Raise to $5,000+ for large-cap focus.

    MAX_DTE_DAYS: int = 60
    # Skip contracts expiring in more than N calendar days.
    # Far-dated contracts (LEAPS) have wide spreads and low sensitivity to near-term flow.
    # 60 days covers the next two monthly expiries. Set to 90+ if you want to track LEAPS flow.

    MAX_MONEYNESS_PCT: float = 0.15
    # Skip contracts where |spot/strike − 1| > N. 15% keeps focus on near-ATM flow
    # (e.g. SPY $550 → $467–$633). Deep OTM/ITM options have unreliable flow signals.

    # Quality confidence penalties: reduce anomaly score when data fields are degraded.
    # Applied multiplicatively after the raw score is computed.
    # The combined penalty is floored at 0.50 (score never reduced by more than 50%).
    SCORE_OI_MISSING_PENALTY: float = 0.10
    # Penalty when open_interest == 0. The VOI component of the score is already zero
    # in this case, but this additionally discounts the overall score to reflect lower confidence.

    SCORE_SPREAD_WIDE_PENALTY: float = 0.05
    # Penalty when (ask − bid) / mid > MAX_BID_ASK_SPREAD_PCT. A wide spread indicates
    # illiquidity; the reported bid/ask may be stale or estimated.

    MAX_BID_ASK_SPREAD_PCT: float = 0.80
    # Threshold for "wide spread": (ask − bid) / mid. 0.80 = 80% spread (e.g. bid $1.00, ask $1.80).
    # Only applied when mid ≥ $0.05 (below that, spread math is unreliable).

    # Alert deduplication / cooldown
    ALERT_COOLDOWN_MINUTES: int = 240
    # Default cooldown window (minutes) after an alert fires.
    # Same-contract alerts within this window are absorbed into the existing alert.
    # 240 min (4 hours) prevents the same contract from spamming the feed within a session.
    # Set to 0 to disable cooldown globally (not recommended).

    # Provider (legacy global default — superseded by per-tenant TenantProviderConfig)
    DATA_PROVIDER: str = "mock"

    # Multi-tenant: default workspace seeded at startup.
    # Fixed UUID so migrations can backfill existing records deterministically.
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"
    DEFAULT_TENANT_SLUG: str = "default"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
