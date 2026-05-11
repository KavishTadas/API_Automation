# Monitoring

## 1. Run Locally

```powershell
npm run monitor:run
```

The monitor reads every JSON collection in `collections/`, runs them with Newman, prints a health summary, and writes failure details to `monitoring/logs/`.

## 2. Set Up A Postman Monitor

1. Open `monitoring/schedule-config.json`.
2. Fill `environmentUid` with the Postman environment UID.
3. Fill `collectionUid` with the Postman collection UID.
4. Update notification emails and Slack webhook details.
5. Use the cron schedule and regions as the template for creating the monitor in your Postman workspace.
6. Save the monitor and confirm it runs against the expected environment.

## 3. Integrate With Datadog

Point a Datadog Synthetic Monitor or log ingestion rule at the JSON output produced by this monitoring flow. The dated `health-YYYY-MM-DD.json` files can be shipped from `monitoring/logs/` so Datadog can alert on failed collections, slow endpoints, and repeated assertion errors.

## 4. Reading Logs

Each `health-YYYY-MM-DD.json` file is a JSON array. Each entry contains:

- `timestamp`: ISO timestamp for the failure.
- `collection`: Newman collection name.
- `requestName`: request or assertion source name.
- `endpoint`: request URL when available.
- `method`: HTTP method when available.
- `statusCode`: response status code when available.
- `responseTimeMs`: response time in milliseconds when available.
- `error`: failure message.
- `expected`: expected assertion value when available.
- `actual`: actual assertion value when available.
