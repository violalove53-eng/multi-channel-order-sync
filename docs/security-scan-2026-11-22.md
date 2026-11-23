**The scan found no critical vulnerabilities, but it did find 2 high-severity data bugs and 1 medium security bug in `connectors/shopify_connector.py`.** I reproduced everything against a fake Shopify server unless noted, and I didn't change any of your code.

| # | Severity | Location | Problem | Result |
|---|---|---|---|---|
| 1 | **High** | `:17`, `:97`, `:109` | **The watermark can get stuck permanently.** With no pagination, a burst of more than 50 orders inside the 15-minute overlap returns the same page every run. | 80 orders, 5 runs: only 50 ever seen, watermark stuck at `00:00:49` |
| 2 | **High** | `:17`, `:109` | **A full sync silently drops orders.** It returns the oldest 50, with no warning. | 120 orders: got #0–#49, newest is #119 |
| 3 | **Medium (security)** | `:98–104` | **The access token can leak on a redirect.** `urllib` resends `X-Shopify-Access-Token` to a different host. This needs the configured domain to redirect, such as a custom domain. | Token reached `other-host.example` |
| 4 | Medium | `:20–33` | **Cancelled orders can't be mapped reliably.** The query omits `cancelledAt`, `processedAt` and `fulfillments`, which your `status`, `paid_at` and `shipped_at` columns need. | Fields confirmed missing; mapping impact not tested on live data |
| 5 | Medium | `:28` | **Orders with more than 20 line items are cut off**, so `raw_payload` isn't really verbatim. | Hard cap, no `pageInfo` |
| 6 | Medium | `:94` | **A naive `since` shifts the time window.** Orders can be skipped if a caller passes `datetime.utcnow()`. | 12:00 UTC became 19:45 in Los Angeles time |
| 7 | Medium | `:104–115` | **There's no retry or dead-letter handling yet**, though the design requires both. | One throttle or bad record aborts the batch |
| 8 | Low | `:48–53` | **`.env` parsing is naive.** It keeps quotes and inline comments, and doesn't understand `export`. | Domain parsed as `"quoted.myshopify.com"` with the quotes |
| 9 | Low | `.env` | **The client secret is readable by other users on this Mac** (mode `644`). | Fix with `chmod 600 .env` |
| 10 | Low | `core/connector.py:10` | **The code crashes on older Pythons.** Your default 3.13 works, but `/usr/bin/python3` and 3.7 fail on import. | `TypeError` |

**What came back clean:**
- `.env` was never committed, and no Shopify tokens appear in git history.
- GraphQL uses variables, so there's no query injection.
- TLS verification is on, and there's no `eval`, shell execution or unsafe deserialization.
- I dropped a suspected bug where a crafted store domain could redirect the client secret, because `urllib` doesn't parse it that way and `.env` is already trusted.

Your 4-order store won't hit #1 or #2 today, and your code comment already plans pagination for tomorrow night. When you add it, loop on `pageInfo.endCursor` and only advance the watermark after the last page, which fixes both.

Fix #3 and #4 next, since #4 determines what gets stored in `raw_payload` from the first real sync.
