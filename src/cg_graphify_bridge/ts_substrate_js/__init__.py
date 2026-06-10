"""Bundled Node assets for the TypeScript type-aware substrate (KD5).

Holds ``extract.cjs`` (the TS-compiler-API extractor). Shipped as package data
(``[tool.setuptools.package-data]``) so a pipx-installed copy resolves it through
``importlib.resources`` rather than a repo-relative ``__file__/parents[*]`` path that
only exists in a source checkout.
"""
