# Sample Design Doc

The **AuthService** handles login and token validation for the platform.
Billing is processed by **BillingService.charge**, which validates the amount.

This doc exists so the semantic overlay (Phase 3) can produce doc→code edges
targeting the composite ids of AuthService / BillingService.
