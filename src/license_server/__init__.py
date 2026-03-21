"""License server for ClipCannon credit billing and HMAC integrity.

Provides a FastAPI-based HTTP server on port 3100 that manages
credit balances with HMAC-SHA256 tamper detection, idempotent charges,
refunds, transaction history, and Stripe webhook handling.
"""
