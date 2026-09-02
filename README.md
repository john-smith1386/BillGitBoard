### 🌐 [Try BillGitBoard →](https://billgitboard.online)

<img src="frontend/public/logo.png" alt="" width="96" align="left" hspace="12" />

# BillGitBoard

BillGitBoard detects a GitHub-style contribution calendar in a screenshot and redraws a short name
into that calendar's own 7-row cell grid. It learns the screenshot's geometry, theme, and
contribution shades from the image itself instead of assuming a fixed resolution or hard-coding
GitHub green.

Upload a screenshot, type a name, pick two colors, download the PNG. No login, no GitHub token, no
account, and nothing is ever committed to any repository.

> GitHub is a trademark of GitHub, Inc. This project is not affiliated with or endorsed by GitHub.

## What it does

1. You upload a reasonably cropped PNG, JPEG, or WebP screenshot of a contribution calendar.
2. The service finds square blobs, locks them to a seven-row lattice, discovers the column count,
   and records partial first and last weeks as absent cells.
3. It samples every cell and clusters the colors in LAB space, producing an empty level plus
   contribution intensity ranks.
4. You type a name, choose a primary and a secondary color, and set outline thickness.
5. A fixed 5x7 bitmap font is laid out only on cells that actually exist.
6. Empty letter cells take the exact secondary color. Letter cells that already hold a contribution
   take a theme-aware primary ramp at the same detected rank.
7. Every non-letter cell keeps its detected color. The result is a clean, freshly drawn calendar
   PNG, not a filter smeared over your screenshot.

The single-page UI shows a detection overlay, a final preview, live fit feedback, optional
start-week placement, a PNG download, and a debug grid JSON download.

## How names are laid out

- Names may use `A-Z`, `0-9`, and spaces. They are trimmed, uppercased, and limited to 24
  characters.
- Letters and digits are five columns wide, spaces are three columns wide, and one column separates
  each pair of alphanumeric glyphs. Spaces add no gap of their own: `AB` is 11 columns, `A B` is 14,
  and `A  B` is 17.
- With `N` alphanumeric glyphs and `S` internal spaces, a name needs `5N + max(0, N-1) + 3S`
  columns. `JOBERNEY` needs `8 x 5 + 7 = 47` of a typical 52- or 53-column graph.
- A name wider than the detected graph is rejected by both the browser and the API.
- Missing partial-week cells are never painted. Placement can shift by up to three weeks to avoid
  them; if it still collides, the render is refused rather than fudged.
- Non-letter cells are never recolored.

## Run it locally

Two paths. Docker is the shortest; running from source is better if you intend to change the code.

### Option A: Docker Compose

Requires Docker Engine or Docker Desktop with Compose v2. The repository ships a template rather
than a ready-made Compose file, so make your own copy first:

```bash
cp docker-compose.example.yml docker-compose.yml
docker compose up --build
```

```powershell
Copy-Item docker-compose.example.yml docker-compose.yml
docker compose up --build
```

Open <http://localhost:8000>. One container serves both the React UI and the API from a single
origin, so there is no CORS setup to do.

The template is deliberately bare: it sets only the port and the data directory, and every other
setting falls back to the application's own default. Uncomment a line in the `environment:` block to
change one. Keep the `"${NAME:-default}"` form when you do - passing a variable through with no
value hands the container an empty string, and it will exit with `... must be numeric` rather than
fall back to the default.

Useful commands:

```bash
# Start in the background
docker compose up --build --detach

# Follow the logs
docker compose logs --follow app

# Check container state
docker compose ps

# Stop, keeping the named data volume
docker compose down

# Rebuild after changing dependencies or source
docker compose build --pull
docker compose up --detach
```

`docker compose down --volumes` also deletes the volume holding every uploaded image, parsed grid,
and render. Use it only when you mean it.

To change non-secret settings, copy `.env.example` to `.env` before starting Compose:

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

### Option B: From source

Requires Python 3.11 or newer (3.12 is the baseline) and Node.js 22. OpenCV comes from the headless
Python wheel, so no system OpenCV installation is needed.

Install the backend:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Install the frontend:

```bash
npm --prefix frontend ci
```

Start the API:

```bash
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000
```

Jobs are written under `./data` by default. Set `BILLGITBOARD_DATA_DIR` to use another path.

Start the UI in a second terminal:

```bash
npm --prefix frontend run dev
```

Open the Vite URL, normally <http://localhost:5173>. Vite proxies `/api` and `/media` to
`http://127.0.0.1:8000`; override that target with `VITE_API_PROXY_TARGET` only if the backend runs
somewhere else.

To serve the built UI from FastAPI on a single port instead:

```bash
npm --prefix frontend run build
BILLGITBOARD_FRONTEND_DIR="$PWD/frontend/dist" uvicorn app.api:app --host 127.0.0.1 --port 8000
```

```powershell
npm --prefix frontend run build
$env:BILLGITBOARD_FRONTEND_DIR = (Resolve-Path .\frontend\dist)
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Then open <http://localhost:8000>. `vite preview` is a build preview only; do not use it as a web
server.

## Deploying with Compose

The same file runs the service on any machine with Docker: your own server, a VPS, a box on your
desk. The image builds the frontend, serves it from FastAPI, and stores jobs on a named volume.

**1. Copy the template and set the build-time values.** Three values are compiled into the frontend
during the image build, so they must be set *before* you build, and changing one later needs a
rebuild rather than a restart. Put them in `.env` at the repository root:

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
```

```ini
# .env
VITE_SITE_URL=https://your-domain.example   # canonical + link previews
VITE_GA_MEASUREMENT_ID=                     # blank ships no analytics tag
VITE_API_BASE_URL=                          # blank keeps the API same-origin
```

**2. Build and start it.**

```bash
docker compose up --build --detach
docker compose ps          # wait for "healthy"
curl --fail http://localhost:8000/health
```

**3. Put TLS in front of it.** The container speaks plain HTTP on one port and does not terminate
TLS. Run a reverse proxy (Caddy, nginx, Traefik) that holds the certificate and forwards to it. Two
settings matter once a proxy is involved:

- Point `FORWARDED_ALLOW_IPS` at that proxy's address. Without it every visitor is counted as the
  proxy, and they all share one rate-limit bucket.
- Do not set it to `*` on a container that is reachable directly, because then any client can claim
  any address in an `X-Forwarded-For` header.

**4. Know where your data is.** Uploaded screenshots, parsed grids, and renders live on the
`billgitboard-data` volume, and expire on their own after the configured TTL. `docker compose down`
keeps the volume; `docker compose down --volumes` destroys it along with every stored image. Back it
up with `docker run --rm -v billgitboard-data:/data -v "$PWD:/backup" busybox tar czf
/backup/billgitboard-data.tgz /data` if the contents matter to you.

**5. Update by rebuilding.**

```bash
git pull
docker compose build --pull
docker compose up --detach
docker compose logs --follow app
```

**Run exactly one instance with one worker.** Rate limits, concurrency guards, and the storage quota
all live in the process, and the job store is a local directory: a second replica would enforce its
own separate limits and would not see jobs the first one wrote. Scale up by giving the single
container more CPU and memory, not by adding containers.

## Using the web interface

1. Crop a screenshot closely enough to include the whole calendar. Month and day labels and the
   Less/More legend are fine to leave in.
2. Drop the image into the upload zone, or pick it from the file dialog.
3. Wait for analysis. You get the row and column count, theme, shade count, palette, warnings, and
   absent-cell count.
4. Toggle the detection overlay and confirm the outlined cells line up with the real graph.
5. Type a name. The browser shows the columns it needs and blocks rendering if it cannot fit; the
   server checks again authoritatively.
6. Pick the primary overlap color and the secondary empty-cell color.
7. Choose 0-8 px outline boldness and, if you want, an explicit start week.
8. Render, inspect the preview, and download the PNG.
9. **Download JSON grid** gives you the parsed grid for debugging. It contains cell colors and
   occupancy, so treat it as mildly sensitive even though it holds no original image bytes.

Good source images are sharp, at least 200x80 pixels, under 15 MB, and show a complete 40-54 column
graph. Heavy compression, browser scaling blur, clipped interior weeks, or a screenshot containing
several unrelated square grids all make detection less reliable.

## HTTP API

Examples assume `http://localhost:8000`. Interactive documentation is at `/api/docs` and the schema
at `/api/openapi.json`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health`, `/api/health` | readiness probe |
| `POST` | `/api/analyze` | multipart upload; detects the grid and returns a `job_id` |
| `POST` | `/api/render` | draws a name onto a previously analyzed job |
| `GET` | `/api/jobs/{job_id}/grid` | the parsed grid as JSON |
| `GET` | `/media/{job_id}/{filename}.png` | source, overlay, and render images |

### Analyze

```bash
curl --fail-with-body \
  --form "file=@./contributions.png" \
  http://localhost:8000/api/analyze
```

On Windows PowerShell, call `curl.exe` explicitly, because `curl` is aliased to `Invoke-WebRequest`.

```json
{
  "job_id": "01J00000000000000000000000",
  "rows": 7,
  "cols": 53,
  "theme": "light",
  "levels": 5,
  "palette": { "0": "#EBEDF0", "1": "#9BE9A8", "2": "#40C463", "3": "#30A14E", "4": "#216E39" },
  "absent_count": 3,
  "preview_original_url": "/media/01J00000000000000000000000/source.png",
  "preview_overlay_url": "/media/01J00000000000000000000000/overlay.png",
  "max_name_columns": 53,
  "warnings": []
}
```

Keep the `job_id`. Rendering works from the analyzed job and never re-detects the screenshot, so the
preview cannot drift from the final image.

Detection errors, and what to do about them:

| Code | Meaning | Fix |
| --- | --- | --- |
| `UNSUPPORTED_MEDIA_TYPE` | not a PNG, JPEG, or WebP | export the screenshot again |
| `CONTENT_TYPE_MISMATCH` | the declared type disagrees with the bytes | send the real media type |
| `EMPTY_FILE` | the upload field had no bytes | pick a non-empty file |
| `IMAGE_TOO_SMALL` | smaller than 200x80 | capture a larger source |
| `INVALID_IMAGE` | the bytes could not be decoded safely | re-export the image |
| `NO_GRID` | too few square blobs, or an unreliable lattice | crop closer, keep all seven rows visible |
| `NOT_SEVEN_ROWS` | seven horizontal bands could not be locked | include the full calendar height |
| `GRID_UNRELIABLE` | the detected lattice falls outside 40-54 columns | use a full year-style graph |

Warnings (`PARTIAL_GRID`, `BLURRY`, `NOT_ENOUGH_SHADES`) report reduced confidence but do not stop a
render.

### Render

```bash
curl --fail-with-body \
  --header "Content-Type: application/json" \
  --data '{"job_id":"JOB_ID","name":"HELLO","primary":"#163951","secondary":"#F5A623","outline":"#0A1620","boldness":2,"start":null}' \
  http://localhost:8000/api/render
```

| Field | Rule |
| --- | --- |
| `job_id` | a live job returned by analyze |
| `name` | trimmed, 1-24 characters, `A-Z`/`a-z`/`0-9`/spaces, stored uppercase |
| `primary` | exact `#RRGGBB`; drives the overlap ramp |
| `secondary` | exact `#RRGGBB`; applied flat to empty letter cells |
| `outline` | exact `#RRGGBB`; defaults to `#0A1620` |
| `boldness` | integer 0-8; defaults to 2 output pixels |
| `start` | `null` to center, or a zero-based week column |

```json
{
  "fit": true,
  "needed_cols": 47,
  "start": 3,
  "letter_cells": 130,
  "overlap_cells": 100,
  "empty_letter_cells": 30,
  "render_url": "/media/01J00000000000000000000000/render-4d0f6c99dd35c2fc8c10dd65.png"
}
```

Refusals are explicit: `NAME_TOO_LONG`, `NAME_OVERFLOW`, `NAME_HITS_ABSENT_CELLS`, `INVALID_NAME`,
`INVALID_COLOR`, `INVALID_BOLDNESS`, `INVALID_START`, and `JOB_EXPIRED`. The render filename is a
deterministic hash of the normalized options, so repeating an identical request returns the same URL
instead of writing another file.

### Grid and media

`GET /api/jobs/{job_id}/grid` returns `rows`, `cols`, `theme`, `levels`, `palette`, `panel_color`,
`absent_count`, warnings, and one record per lattice position:

```json
{ "r": 0, "c": 0, "level": 0, "rgb": "#EBEDF0", "present": true }
```

`rgb` is that cell's measured median color; `level` is the only value used to match contribution
intensity while recoloring. Absent records are never painted.

Media URLs come back from analyze and render. Only safe PNG filenames inside a live job resolve.

## Local configuration

The API reads process environment variables. `.env.example` documents the full set and is what
Docker Compose interpolates; a plain `uvicorn` run does not load it automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` in the container | listener port |
| `BILLGITBOARD_DATA_DIR` | `./data` locally, `/data` in the container | writable job and media root |
| `BILLGITBOARD_JOB_TTL_HOURS` | `24` | how long jobs and their media survive |
| `BILLGITBOARD_MAX_UPLOAD_MB` | `15` | accepted upload size |
| `BILLGITBOARD_MAX_JSON_BODY_KB` | `64` | ceiling for JSON request bodies, enforced before the body is buffered or parsed |
| `BILLGITBOARD_CLIENT_IP_HEADER` | empty | opt in to trusting one edge-set header (e.g. `cf-connecting-ip`) as the rate-limit key |
| `BILLGITBOARD_FRONTEND_DIR` | unset locally, `/app/frontend/dist` in the image | built SPA served by FastAPI |
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8000` | Vite development proxy destination |
| `VITE_API_BASE_URL` | empty | API origin compiled into the frontend build |
| `VITE_SITE_URL` | `https://billgitboard.online` | public origin baked into the canonical link, link-preview tags, and structured data |
| `VITE_GA_MEASUREMENT_ID` | empty | Google Analytics ID compiled into `index.html`; empty ships no analytics tag at all |

There are no required secrets, API keys, GitHub tokens, or databases. Vite values are baked in at
build time, so rebuild the frontend after changing any `VITE_` value.

Jobs live on the filesystem, and analyze and render must be served by the same process reading the
same directory, so run one instance with one worker.

## Tests

From the repository root, with the development dependencies installed:

```bash
python -m pytest
python -m ruff check app tests scripts
npm --prefix frontend test
npm --prefix frontend run build
```

To write the synthetic calendar fixtures to disk for manual inspection:

```bash
python scripts/generate_test_fixtures.py
```

Coverage includes real GitHub-rendered light graphs at 0.5x, 1x, and 2x, generated light and dark
palettes, a non-green theme, partial first and last weeks, rejection of out-of-range lattices, fit
and collision cases, palette ranking, and the API response contracts.

## Make it yours

### Footer links, support button, and project list

Every outbound link in the footer lives in one file:
[`frontend/src/siteLinks.ts`](frontend/src/siteLinks.ts). Nothing in it is required.

```ts
export const supportLink: SiteLink | null = {
  label: "Support this project",
  href: "https://plantyourtip.com/g2FfQQIl5d",
  logo: "/logos/plantyourtip.png",
};

export const otherProjects: SiteLink[] = [
  { label: "Joberney", href: "https://joberney.com/", logo: "/logos/joberney.png" },
];

export const builtBy: SiteLink | null = {
  label: "Novarima LLC",
  href: "https://novarima.com/",
};
```

- **Change a link:** edit its `label` and `href`.
- **Remove the support badge or the credit:** set `supportLink` or `builtBy` to `null`.
- **Remove the project list:** empty the `otherProjects` array (`[]`).
- **Remove all of it:** do all three, and the footer keeps only its product line.

Rebuild the frontend after any change: `npm --prefix frontend run build`.

### Logos

Logo images live in [`frontend/public/logos/`](frontend/public/logos/) and are served at
`/logos/<file>`. They are bundled with the app rather than hotlinked, so drawing the footer never
sends a visitor's browser to a third-party host. A `logo` value can also be an absolute `https://`
URL if you prefer that tradeoff.

**A missing logo is not a broken image:** if the file fails to load, the footer quietly shows the
text label instead. Delete every file in that folder and the footer still renders correctly.

To add your own, drop a transparent PNG or SVG into `frontend/public/logos/`, point the entry's
`logo` at it, and rebuild. Logos render 15 px tall, so roughly 96-120 px tall is plenty.
[`frontend/public/logos/README.md`](frontend/public/logos/README.md) documents each file and where
it came from.

The same applies to this README: the links under [Support](#support) and
[Also from us](#also-from-us) are plain Markdown. Edit or delete those two sections and the badge
below them to make the project yours.

### Browser icon

The favicon, Apple touch icon, and web-app icons are generated from the same navy-and-amber mark as
the header logo:

```bash
python scripts/generate_icons.py
```

That writes `favicon.ico`, `favicon-96x96.png`, `apple-touch-icon.png`, and both
`web-app-manifest-*.png` files into `frontend/public/`. Change the colors or the cell pattern at the
top of `scripts/generate_icons.py` and rerun it, keeping the hand-written
`frontend/public/favicon.svg` in step. To use your own artwork instead, replace those files directly
and leave the `<link>` tags in `frontend/index.html` alone. The installed-app name and description
live in `frontend/index.html` and `frontend/public/site.webmanifest`.

### Search visibility and link previews

`frontend/index.html` carries the page title, meta description, canonical link, Open Graph and
Twitter card tags, and a `WebApplication` JSON-LD block. Absolute URLs in those tags are not
hard-coded: the head uses a `%SITE_URL%` placeholder that a small plugin in `frontend/vite.config.ts`
fills in at build time.

**Set your origin before deploying.** Put it in `.env` (or the platform's environment) and rebuild:

```bash
VITE_SITE_URL=https://your-domain.example npm --prefix frontend run build
```

The default is `https://billgitboard.online`. Pointing a canonical link at a hostname that does not
resolve can keep the page out of search results entirely, so set this to the origin actually serving
the site - including a temporary one like `https://your-app.onrender.com` - and change it again when
you move to a custom domain.

The 1200x630 preview image is generated, not drawn by hand:

```bash
python scripts/generate_og_image.py
```

It renders the word in the panel with the very glyphs the service uses, and asserts its own layout
against `app.text.layout.needed_columns`, so the card cannot drift from what the renderer would
produce. Change `WORD`, `HEADLINE`, or `SUBLINE` at the top of the script and rerun it. Replace
`frontend/public/og-image.png` directly if you would rather supply your own artwork; keep it 1200x630
so the `og:image:width`/`height` tags stay truthful.

`robots.txt` and `sitemap.xml` are generated at build time by the same plugin, because both need the
absolute origin and files in `frontend/public/` are copied through untouched. `robots.txt` allows the
app, disallows `/api/` and `/media/` so crawlers stay out of uploaded screenshots and rendered PNGs,
and points at the sitemap. The dev server serves both too, so what you test locally is what deploys.

`index.html` also carries a `<noscript>` block describing the service, so a crawler that does not run
JavaScript still sees what the page is about rather than an empty `<div>`.

### Analytics

**Analytics is off by default, and no measurement ID is committed to this repository.** A Google
Analytics tag sits at the bottom of `frontend/index.html`, between the `analytics:start` and
`analytics:end` comments, but it is inert until you supply an ID of your own. Build with no ID and
the entire block is deleted from the built HTML - not loaded and disabled - so no request reaches
Google and no page view can land in anyone else's property.

To turn it on, set `VITE_GA_MEASUREMENT_ID` to your own `G-XXXXXXXXXX` and rebuild:

```bash
VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX npm --prefix frontend run build
```

For a persistent local setting, put it in `.env` (which is git-ignored). For a deployment, set it in
the platform's environment rather than in a file: the value is compiled into the HTML at **build**
time, so changing it requires a rebuild, not just a restart.

| Where you build | How to set it |
| --- | --- |
| Local `npm run build` | `.env` at the repository root, or inline on the command line |
| `docker compose` | `.env` at the repository root; Compose forwards it as a build argument |
| `docker build` | `--build-arg VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX` |
| Render, Fly, and similar | a service environment variable; the `ARG` in the Dockerfile receives it |

To turn analytics back off, clear the variable and rebuild.

The tag is only injected by `vite build`. The dev server serves the page without it, so local
development never shows up in your reports.

Loading Google Analytics sets cookies and sends visitor data to a third party. Depending on where
your visitors are, that may require a consent banner and a privacy notice; leaving the variable
unset is the simplest way to avoid the question entirely.

### Product name and copy

The header wordmark, hero copy, and footer text are plain JSX in `frontend/src/App.tsx`. The colors
and the grid mark itself are CSS variables at the top of `frontend/src/styles.css`.

## Support

If this saved you some time, you can leave a tip:

<a href="https://plantyourtip.com/g2FfQQIl5d"><img src="https://cdn.plantyourtip.com/assets/PlantYourTipL2.png" alt="PlantYourTip" style="width: 100px; height: auto;"></a>

Stars, issues, and pull requests are just as welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before
changing detection or rendering behavior.

## Also from us

<p>
  <a href="https://joberney.com/"><img src="frontend/public/logos/joberney.png" alt="Joberney" height="46"></a>
  &nbsp;&nbsp;
  <a href="https://beadela.com/"><img src="frontend/public/logos/beadela.png" alt="Beadela" height="46"></a>
  &nbsp;&nbsp;
  <a href="https://kindnesssender.com/"><img src="frontend/public/logos/kindnesssender.png" alt="KindnessSender" height="46"></a>
</p>

- [Joberney](https://joberney.com/) - career and side-hustle tools: resumes, cover letters, business
  ideas, and market research in one place.
- [Beadela](https://beadela.com/) - turns any photo into a buildable bead pattern with color-matched
  beads and printable instructions.
- [KindnessSender](https://kindnesssender.com/) - send an anonymous kind message to a stranger who
  may be having a hard day.

## License

BillGitBoard is released under the [MIT License](LICENSE). The documented
`tests/fixtures/official_github_light.png` asset is not relicensed under MIT; see
[fixture provenance and terms](tests/fixtures/README.md).

---

Built by **[Novarima LLC](https://novarima.com/)**
