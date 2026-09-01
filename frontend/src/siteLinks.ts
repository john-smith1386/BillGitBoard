/**
 * Optional footer links: support, sibling projects, and the maintainer credit.
 *
 * Everything in this file is safe to edit or delete. Set `supportLink` or
 * `builtBy` to `null`, or empty the `otherProjects` array, and the matching
 * footer content disappears without any other change. When every value is
 * removed the footer keeps only the product line it had before.
 *
 * `logo` is optional in every entry. A path such as "/logos/joberney.png"
 * resolves to `frontend/public/logos/joberney.png`; an absolute `https://` URL
 * loads from that origin instead, which sends a request from every visitor's
 * browser to that host. A logo that fails to load is hidden and the text label
 * is shown alone, so an entry never renders as a broken image.
 *
 * Vite compiles these values into the built assets, so rebuild the frontend
 * after changing them.
 */

export interface SiteLink {
  /** Visible text. Always rendered, so it doubles as the logo's fallback. */
  label: string;
  /** Absolute destination URL. */
  href: string;
  /** Optional image: a path under `frontend/public` or an absolute URL. */
  logo?: string;
}

/** Donation/tip link. Set to `null` to remove the support badge entirely. */
export const supportLink: SiteLink | null = {
  label: "Support this project",
  href: "https://plantyourtip.com/g2FfQQIl5d",
  logo: "/logos/plantyourtip.png",
};

/** Heading shown before the project list. */
export const otherProjectsLabel = "Also from us";

/** Sibling projects. Delete entries, add your own, or empty the array. */
export const otherProjects: SiteLink[] = [
  { label: "Joberney", href: "https://joberney.com/", logo: "/logos/joberney.png" },
  { label: "Beadela", href: "https://beadela.com/", logo: "/logos/beadela.png" },
  {
    label: "KindnessSender",
    href: "https://kindnesssender.com/",
    logo: "/logos/kindnesssender.png",
  },
];

/** Maintainer credit. Set to `null` to remove the "Built by" line. */
export const builtBy: SiteLink | null = {
  label: "Novarima LLC",
  href: "https://novarima.com/",
};

export const hasFooterLinks =
  supportLink !== null || builtBy !== null || otherProjects.length > 0;
