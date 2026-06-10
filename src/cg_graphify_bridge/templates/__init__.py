"""Shipped templates installed into a target repo by `cg-graphify-bridge init` (KD13).

Currently: ``graph-build.yml`` — the GitHub Actions workflow that builds the deterministic
structural layer and commits it onto the PR's own branch. Shipped as package data so a
pipx-installed copy resolves it through ``importlib.resources`` (same pattern as the TS
extractor in ``ts_substrate_js``).
"""
