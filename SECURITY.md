# Security Incident Response: Report Credential Exposure

## Required remediation

Previously generated HTML, Allure, JSON, and other test-report artifacts may
contain an employee code or password in plaintext. Treat every such report as
sensitive until it has been reviewed and removed.

1. Purge all affected generated reports from local workspaces and CI artifact
   storage, including GitHub Actions, Jenkins, and any external artifact
   archive. Remove historical report artifacts, not only the most recent run.
2. If a report or artifact containing the exposed credential was committed to
   Git, remove it from the reachable Git history using the repository's
   approved history-rewrite process, then force-push the cleaned history and
   notify affected clone owners to re-clone or repair their local copies.
3. Rotate the exposed employee credential in the HCM/identity system. This is
   a manual action for the repository owner or the responsible identity
   administrator; it cannot be performed from this repository.
4. After rotation and cleanup, invalidate obsolete CI artifacts and rerun the
   report-redaction verification before publishing new reports.

## Handling rule

Do not copy, paste, record, or add the employee code, password, token, or any
other secret to this repository, issue tracker, build log, or documentation.
