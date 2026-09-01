# Real-world fixture provenance

## `official_github_light.png`

- Source: [GitHub Docs contribution graph image](https://docs.github.com/assets/cb-35216/images/help/profile/contributions-graph.png)
- Retrieved: 2026-08-31
- Original filename: `contributions-graph.png`
- Format and dimensions: PNG, RGB, 1536 x 398 pixels
- File size: 35,216 bytes
- SHA-256: `bb99807fc13336f50ee13e852fcb2e4bbe8a185545922d667e6e3097ce508841`
- Test purpose: real-world, light-theme integration coverage for contribution-grid detection, partial first-week occupancy, shade ranking, and literal Lanczos resize stability.

This binary is intentionally committed because generated fixtures cannot capture every anti-aliasing, border, typography, and spacing characteristic of a real GitHub-rendered graph. Do not modify or optimize it in place. If the upstream fixture is deliberately refreshed, record the new retrieval date, dimensions, byte length, hash, and reason, then review all expected grid ranks rather than automatically accepting changed output.

GitHub and the GitHub logo are trademarks of GitHub, Inc. This project is not affiliated with or endorsed by GitHub. The image remains subject to GitHub's applicable copyright and trademark terms; its inclusion here for focused interoperability and regression testing does not relicense the image under this repository's MIT License.

