"""Billing module (sample fixture)."""


def process(amount):
    """Top-level process() — same qualified_name as pkg_a.auth.process but
    different file_path; composite key must keep them distinct."""
    return BillingService().charge(amount)


class BillingService:
    def charge(self, amount):
        return amount > 0
