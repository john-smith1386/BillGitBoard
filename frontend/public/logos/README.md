# Footer logos

Files here are served at `/logos/<file>` and referenced from
[`frontend/src/siteLinks.ts`](../../src/siteLinks.ts). Nothing here is required:
a link whose image is missing renders as its text label instead, so removing a
file degrades gracefully rather than breaking the footer.

## What is here

| File | Used by | Source |
| --- | --- | --- |
| `joberney.png` | Joberney project link | `novarima.com/assets/joberney-logo-1400.png`, resized to 120 px tall |
| `beadela.png` | Beadela project link | `novarima.com/assets/beadela-b.png`, resized to 120 px tall |
| `kindnesssender.png` | KindnessSender project link | `novarima.com/assets/kindnesssender-logo.png`, resized to 120 px tall |
| `plantyourtip.png` | support badge | `cdn.plantyourtip.com/assets/PlantYourTipS2.png`, unmodified |

All four have transparent backgrounds. They are copied in rather than hotlinked
so that no visitor's browser has to reach a third-party host to draw the footer.
Re-fetch the originals from the source URLs above if you need full resolution.

There is no `novarima.png`: Novarima publishes only white-background artwork, so
the "Built by" credit is a text link. Add the file and give `builtBy` a `logo`
value if that changes.

## Add, change, or remove one

Drop in a transparent PNG or an SVG, then edit
[`frontend/src/siteLinks.ts`](../../src/siteLinks.ts):

- point `logo` at another filename, or at an absolute `https://` URL to load it
  from elsewhere;
- delete the `logo` property to keep the link as text only;
- delete the whole entry, or set `supportLink`/`builtBy` to `null`, to drop the
  link entirely.

The footer draws logos 15 px tall and at most 64 px wide, so roughly 96-120 px
tall is enough for a high-density screen. Keep the files small; they load on
every page view.

Rebuild afterwards with `npm --prefix frontend run build`. Vite compiles the
config values into the built assets.

The browser tab icons in the parent folder are generated instead of hand-edited:
see [`scripts/generate_icons.py`](../../../scripts/generate_icons.py).
