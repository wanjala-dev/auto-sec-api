"""Subscription bounded context — plan definitions, quota enforcement, and subscription lifecycle.

Owns the concept of "what can a team/workspace do" (plan limits, features).
Delegates payment processing (Stripe, checkout, webhooks) to the payments context.
"""
