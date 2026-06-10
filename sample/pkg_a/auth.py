"""Auth module (sample fixture)."""


def process(token):
    """Top-level process() — DELIBERATELY same name as pkg_b.billing.process
    to exercise cross-file qualified_name collision (qn='process' in both)."""
    return AuthService().login(token)


def process_helper(token):
    return token is not None


class AuthService:
    def login(self, token):
        return process_helper(token)
