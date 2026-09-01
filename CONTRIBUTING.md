# Contributing to BillGitBoard

Thanks for improving the contribution overlay service. The project is generic:
tests and product copy should not assume any one organization, repository, or
brand. A name such as `JOBERNEY` is useful test data, not product identity.

## Development setup

Install Python 3.11 or newer and Node.js 22, then run:

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

cd frontend
npm ci
cd ..
```

Start the API with `uvicorn app.api:app --reload --port 8000` and the UI in a
second terminal with `npm --prefix frontend run dev`. Vite proxies `/api` and
`/media` to the API, so CORS is not required for the normal setup.

Before opening a pull request, run:

```bash
python -m pytest
python -m ruff check app tests scripts
npm --prefix frontend test
npm --prefix frontend run build
docker build -t billgitboard:check .
```

## Vision and rendering changes

- Do not assume a pixel cell size, 53 columns, GitHub green, or a light theme.
- Do not recolor non-letter cells, paint absent dates, or re-detect the grid at
  render time. The analyzed job artifact is the render source of truth.
- Add a deterministic synthetic fixture when introducing a new visual case.
  Run `python scripts/generate_test_fixtures.py` to inspect those fixtures.
  The committed official documentation fixture has separate provenance and
  refresh rules in `tests/fixtures/README.md`; never replace it silently.
- Compare results in cell-index space and inspect the inner 60%/80% regions
  described by the specification; anti-aliased rounded corners are not stable
  color samples.
- Preserve the public error-code contract when refining user-facing messages.

## Pull requests

Keep changes focused, explain the user-visible behavior, and include the tests
that fail without the change. Never commit real user screenshots, the runtime
`data/` directory, `.env` files, access tokens, or generated renders. Call out
any intentional API response or configuration change in the pull request.

By contributing, you agree that your contribution is licensed under the
repository's MIT License.
