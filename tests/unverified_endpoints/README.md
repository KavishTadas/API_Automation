# Unverified endpoint checks

This directory preserves checks for endpoints that are not part of the
authoritative HCM OpenAPI contract. The HCM CI suite runs only
`tests/auto_generated`, so files here are excluded. They also carry explicit
pytest skip markers to remain safe during broader local test discovery.
