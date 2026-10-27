# CLAUDE.md

## Releasing a new version

1. Bump the version in `pyproject.toml`, `__version__` in `aiohttp_request_id_logging/__init__.py`
   and the project's own entry in `uv.lock` (`uv lock --check` must pass).
2. In the README "Version changelog", rename `### Unreleased` to `### X.Y.Z (YYYY-MM-DD)`.
3. Run `make check`, commit as `Version X.Y.Z` and add a lightweight tag `vX.Y.Z`.
4. Right after the tag, in a separate commit `README: Start changelog section for next version`,
   open a new section at the top of the changelog:

   ```markdown
   ### Unreleased

   - Nothing yet :)
   ```

   It stays out of the tagged commit because the README is the PyPI project description.

Publishing a GitHub release for the tag runs `.github/workflows/pypi.yml`, which uploads the package to PyPI.
