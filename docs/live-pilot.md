# Money Tree LIVE execution check

Approved trial: $50 initial cash, $25 loss cutoff, one bot and one YES contract at 3 cents. The pilot makes at most one entry attempt. It does not automatically expand to the other 27 bots or retry into another market. The copied full-size allocations remain planning figures during this check.

## Connect

1. Use Kalshi production, not Demo. Generate a dedicated API key in [Kalshi Profile Settings](https://kalshi.com/account/profile) and save the key ID and private key immediately.
2. Prepare a numbered subaccount and place exactly $50 cash there, with no other orders or positions. Kalshi subaccounts are API-only; creating one requires Advanced API access. Follow [Kalshi's subaccount documentation](https://docs.kalshi.com/getting_started/subaccounts) and [Create Subaccount](https://docs.kalshi.com/api-reference/portfolio/create-subaccount). Setup/funding is controlled by the account owner; the trading worker cannot transfer money.
3. Generate a separate key restricted to that numbered subaccount, with `read` and `write::trade` scopes, using [Generate API Key](https://docs.kalshi.com/api-reference/api-keys/generate-api-key). Do not give Money Tree an unrestricted setup key. Restricted keys cannot move money between subaccounts.
4. In **LIVE BOTS → Secure LIVE connection**, enter the restricted key ID, numbered subaccount and private-key file (or paste its PEM text). Select **Verify and save LIVE connection**. The form clears the private key after the attempt. The backend encrypts it separately from Demo credentials and never returns it to the browser.
5. Choose the pilot bot and select **Check account readiness**. The check verifies that at least 3 cents of the existing $50 is available on the current market’s exchange index. If needed, it reports the index to use in Kalshi’s API setup; the worker never moves cash between indexes. This is read-only; connecting or preflighting does not pause Demo or place an order.
6. Only the owner can manually request the real-money check by typing `START ONE LIVE CONTRACT` and pressing the start button. Preflight expires after 60 seconds and settings/account changes invalidate it.

## Exclusive handover

Starting the check pauses every Demo bot. Existing buys cancel while held Demo contracts keep their original management. LIVE waits for fresh reconciliation, no unresolved current-market Demo writes, no resting exchange orders (including manual orders), and no exchange positions. Verified closed, flat historical records stay searchable without preventing handover; a local expiry alone is insufficient. The same advisory fence is released by Demo before LIVE can acquire it. Resume, bulk resume and reset undo cannot restart Demo during handover or LIVE operation.

The worker never runs both environments simultaneously. A pause stops new LIVE buys and cancels waiting buys; filled contracts retain their exits. Returning to Demo is blocked until LIVE is verified flat. Demo bots remain paused until explicitly resumed.

## Execution and recovery

- Buy: one YES contract, 3-cent limit, maker-only, exchange expiry at five minutes after the market opens. No price-chasing or entry repeats during the pilot.
- Exit: in the final five minutes, a positive held-side bid below 40 cents latches an exit; maker sell one cent above bid, rounded up to the market's tick. At or above 40 cents before the trigger, hold. Empty bids do not fabricate a 1-cent sale.
- Repricing: down only; cancel when the resting sell exceeds the current bid by more than five cents, verify the cancellation/fills, then replace only the remaining inventory. A rebound does not raise the saved limit.
- Durable intent and a separate write claim precede HTTP. An uncertain response never permits replaying the write. An exchange acceptance is not a fill.
- The worker verifies owned inventory before a sell and prevents simultaneous resting sells. Kalshi's V2 reduce-only flag is not used because it is incompatible with resting maker orders.
- New entries require a verified control backup and a zero-maker-fee schedule including event overrides and scheduled changes. Existing exits continue if a later backup fails.
- The $25 cutoff reserves worst-case open-contract cost against realized results. It stops new buys; it is not a guaranteed $25 maximum loss after open exposure or fees.
- Statistics and credentials use a separate `live/` namespace. Backups include LIVE controls, trial, write claims and the complete pilot order ledger, excluding credentials.

## Release verification

Local unit, gateway and browser checks must pass. PostgreSQL transaction tests and deployed health checks must pass before describing the release as ready. An actual accepted buy, fill, cancel, conditional exit and settlement can only be verified after the owner connects the real account and manually starts the pilot. No real order is submitted as part of software verification or deployment.
