# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use the
repository's **Security → Report a vulnerability** workflow if private
vulnerability reporting is enabled. Otherwise, contact the maintainer through
the private contact method listed on the repository owner profile and include:

- the affected version or commit;
- a minimal reproduction;
- the expected impact;
- any suggested mitigation; and
- whether the report or proof contains a real uploaded screenshot.

Do not include credentials, private contribution screenshots, or personally
identifying image content unless the maintainer explicitly requests it through
a secure channel.

## Deployment security notes

BillGitBoard is intentionally unauthenticated in v1. Treat every public
deployment as an internet-facing upload processor.

- Keep the 15 MB file limit, 16 MiB pre-parser request cap, 16-million decoded
  pixel cap, and one-at-a-time analyze concurrency enabled. Enforce the same
  total body cap and bounded upload time at the public reverse proxy.
- Keep both analyze and render per-IP limits enabled. Preserve the per-job
  render-variant cap and a total artifact quota below the actual volume size.
- Use at least the documented 2 GB production memory baseline unless the exact
  maximum file/pixel/concurrency settings have been load-tested on less.
- Terminate TLS at the hosting platform or a trusted reverse proxy.
- Trust forwarded IP headers only from that proxy. A directly exposed Uvicorn
  process should not use a wildcard `FORWARDED_ALLOW_IPS` value.
- Mount only the dedicated data directory read/write. The container bootstrap
  accepts only `/data` (or a child) or a dedicated child of `/var/data`, refuses
  `/` and unrelated paths, and changes ownership only inside that resolved path.
- Managed-volume deployments may start the bootstrap as root, after which
  `setpriv` uses `CAP_SETPCAP` to discard the bounding, permitted, effective,
  inheritable, and ambient capability sets. The entrypoint verifies that all
  are zero before it runs Uvicorn as UID/GID 10001 with `no_new_privs`.
  Docker Compose starts directly as 10001:10001 with all capabilities dropped.
- Never log image bodies, extracted metadata, or media URLs. Logs should contain
  only job IDs, dimensions, shade counts, name length, status, and timings.
- Jobs and media expire after 24 hours by default. Backups of a persistent
  volume can retain images longer, so define and document a backup retention
  policy that matches your privacy promise.
- The filesystem store is single-instance. Do not horizontally scale it behind
  a load balancer unless jobs and rate-limit state are moved to shared stores.
- Keep Pillow, OpenCV, FastAPI, Uvicorn, NumPy, and scikit-learn patched. Image
  parsers are a meaningful attack surface even when EXIF is stripped.

Supported versions are the latest release and the current default branch.
