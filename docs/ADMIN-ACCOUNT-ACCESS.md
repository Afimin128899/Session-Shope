# Admin account and order access

Stock rows now link to the latest order for the account, including buyer ID,
purchase date and actual paid amount. Search stock by order number; search orders
by order, buyer, account, username or phone. Open order details for warranty,
refund, support and the latest 50 audited actions. Legacy missing values are
shown as not saved; purchase dates retain their original Moscow-time value.
Administrative timestamps are UTC.

Database initialization adds nullable `access_revoked_at`, `access_revoked_by`
and `access_revoked_reason` columns to purchases. Restart the updated application
before using the UI so the existing schema initialization runs.

1. Open an order and choose **Отозвать доступ через магазин**, supplying a reason.
   This blocks further login codes and hides the password through the bot and
   Mini App without deleting the retained store session or changing financial
   history. Repeated requests preserve the original actor, time and reason.
2. For an issued order with shop access revoked, optionally choose
   **Завершить другие сеансы Telegram** and confirm the order number. The existing
   Telegram service checks the account's identity, preserves the store's current
   authorization, resets other authorizations and verifies the remaining list.
3. Reopen details to inspect the recorded Telegram result. `cleaned` and `single`
   mean no other authorizations were observed in the final check. `failed` means
   cleanup was not confirmed; shop access stays revoked. Partial cleanup is
   possible when Telegram rejects a later reset.

These actions cannot erase previously delivered codes/passwords, restore a
session deleted on completion, or guarantee continued ownership of a Telegram
account. A copied authorization with the same key as the store is not a separate
Telegram session and cannot be terminated independently. Telegram can reject
termination, including because of authorization age or rate limits. No automatic
resale, refund, credential export or admin impersonation is performed.

Only the existing full-admin API role can access these endpoints. Requests use
POST with JSON at `/api/admin/orders/{id}/revoke-access` (`reason`) and
`/api/admin/orders/{id}/terminate-sessions` (empty object). Cleanup holds the
purchase/account locks during the bounded Telegram call to serialize it with
completion, replacement and refunds. External Telegram resets cannot be rolled
back if a subsequent database/audit commit fails; inspect Telegram before retrying.
