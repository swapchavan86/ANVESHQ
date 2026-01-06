# Nexara: Next-Era Market Intelligence Platform

Nexara is a Python-based market intelligence system that provides daily insights into the stock market. It consists of two main components:

*   **Rootset**: A weekly job that builds the canonical universe of stocks.
*   **Fluxmind**: A daily intelligence engine that scans the market and identifies trading signals.

## Configuration

This project uses `pydantic-settings` to manage configuration. Settings can be provided via environment variables or a local `.env` file.

**Precedence Order:**

1.  **Environment Variables**: Highest priority. These will always override any other settings.
2.  **.env File**: Used for local development.
3.  **Default Values**: Lowest priority, defined directly in `Backend/src/config.py`.

### Local Development

For local development, create a `.env` file inside the `Backend` directory by copying the example file:

```bash
cp Backend/.env.example Backend/.env
```

Then, edit `Backend/.env` with your local configuration, such as your database connection strings.

### Required Environment Variables/Secrets

The following variables must be set in your `.env` file for local runs or as secrets in your CI/CD environment (e.g., GitHub Actions):

*   `MODE`: The execution mode (`DEV`, `PROD`, or `TEST`). Defaults to `DEV`.
*   `DATABASE_URL`: The connection string for the primary database.
*   `TEST_DATABASE_URL`: The connection string for the test database (optional, only needed for running tests).
*   `LOG_LEVEL`: The logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Defaults to `INFO`.
*   `NSE_EQUITY_LIST_URL`: URL for the NSE equity list.
*   `NSE_NIFTY500_CSV_URL`: URL for the NIFTY 500 CSV.
*   `BSE_CM_CSV_URL`: URL for the BSE CM CSV.
*   `BHAVCOPY_URL_TEMPLATE`: Template URL for the Bhavcopy.
*   `FUNDAMENTAL_CHECK_ENABLED`: Boolean to enable/disable fundamental check.
*   `MIN_PRICE`: Minimum price of the stock.
*   `MIN_MCAP_CRORES`: Minimum market cap in crores.
*   `STREAK_THRESHOLD_DAYS`: Streak threshold in days.
*   `NEAR_52_WEEK_HIGH_THRESHOLD`: Threshold for nearness to 52-week high.
*   `VOLUME_CONFIRMATION_FACTOR`: Volume confirmation factor.
*   `RELATIVE_LIQUIDITY_FACTOR`: Relative liquidity factor.
*   `MAX_RANK`: Maximum rank for a stock.
*   `DECAY_FACTOR`: Decay factor for the rank.

When running in a CI environment like GitHub Actions, these values should be set as environment variables or secrets, and the `.env` file will be ignored.
