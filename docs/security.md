# Security Tracker

## Status Definitions

| Status | Meaning |
|---|---|
| Open | Confirmed, work not started |
| In Progress | Fix underway |
| Fixed | Fixed, with the fix commit recorded |
| Accepted | Assessed and decided not to fix |
| False Positive | Not a real issue |

## Findings

| ID | Date Found | Issue | Severity | Status | Fix Commit | Notes |
|---|---|---|---|---|---|---|
| SEC-001 | 2026-11-22 | Watermark can get stuck permanently: with no pagination, more than 50 orders inside the 15-minute overlap window return the same page every run | High | Open | | `connectors/shopify_connector.py:17`, `:97`, `:109`; 80 orders over 5 runs: only 50 seen, watermark stuck at `00:00:49` |
| SEC-002 | 2026-11-22 | Full sync silently drops orders: only the oldest 50 are returned, with no warning | High | Open | | `connectors/shopify_connector.py:17`, `:109`; 120 orders: got #0–#49, newest is #119 |
| SEC-003 | 2026-11-22 | Access token can leak on redirect: `urllib` forwards `X-Shopify-Access-Token` to a different host | Medium | Open | | `connectors/shopify_connector.py:98–104`; security issue; only triggers if the configured domain redirects (e.g. a custom domain) |
| SEC-004 | 2026-11-22 | Cancelled orders can't be mapped reliably: the query omits `cancelledAt`, `processedAt` and `fulfillments` | Medium | Open | | `connectors/shopify_connector.py:20–33`; affects `status`, `paid_at`, `shipped_at`; missing fields confirmed, mapping impact not tested on live data |
| SEC-005 | 2026-11-22 | Orders with more than 20 line items are truncated, so `raw_payload` is not fully verbatim | Medium | Open | | `connectors/shopify_connector.py:28`; hard cap, `pageInfo` not requested |
| SEC-006 | 2026-11-22 | A naive `since` shifts the time window; orders can be skipped if a caller passes `datetime.utcnow()` | Medium | Open | | `connectors/shopify_connector.py:94`; in Los Angeles time, 12:00 UTC became 19:45 |
| SEC-007 | 2026-11-22 | Retry and dead-letter handling are not implemented, though the design requires both | Medium | Open | | `connectors/shopify_connector.py:104–115`; one throttle or bad record aborts the whole batch |
| SEC-008 | 2026-11-22 | `.env` parsing is naive: keeps quotes and inline comments, doesn't support `export` | Low | Open | | `connectors/shopify_connector.py:48–53`; reproduced with test values |
| SEC-009 | 2026-11-22 | Client secret is readable by other users on this machine (`.env` mode `644`) | Low | Open | | Fix: `chmod 600 .env`; a local permission change produces no commit |
| SEC-010 | 2026-11-22 | Crashes on import under older Python: default 3.13 works, `/usr/bin/python3` and 3.7 raise `TypeError` | Low | Open | | `core/connector.py:10` |

## Scan Log

| Date | Tool | Scope | Report |
|---|---|---|---|
| 2026-11-22 | Claude-BugHunter | Full project, focus on `connectors/shopify_connector.py` | [docs/security-scan-2026-11-22.md](security-scan-2026-11-22.md) |
