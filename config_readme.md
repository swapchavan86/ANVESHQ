### Configuration

This project uses `pydantic-settings` to manage configuration. Settings can be provided via environment variables or a local `.env` file.

**Precedence Order:**

1.  **Environment Variables**: Highest priority. These will always override any other settings.
2.  **.env File**: Used for local development.
3.  **Default Values**: Lowest priority, defined directly in `Backend/src/config.py`.

#### Local Development

For local development, create a `.env` file inside the `Backend` directory by copying the example file:

```bash
cp Backend/.env.example Backend/.env
```

Then, edit `Backend/.env` with your local configuration, such as your database connection strings.

**Required Environment Variables/Secrets:**

The following variables must be set in your `.env` file for local runs or as secrets in your CI/CD environment (e.g., GitHub Actions):

*   `MODE`: The execution mode (`DEV`, `PROD`, or `TEST`). Defaults to `DEV`.
*   `DATABASE_URL`: The connection string for the primary database.
*   `TEST_DATABASE_URL`: The connection string for the test database (optional, only needed for running tests).
*   `LOG_LEVEL`: The logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Defaults to `INFO`.

When running in a CI environment like GitHub Actions, these values should be set as environment variables or secrets, and the `.env` file will be ignored.
