import { describe, expect, it } from "vitest";
import {
  approximateLetterHint,
  neededColumns,
  normalizeName,
  validateName,
} from "./fontMetrics";

describe("name grid metrics", () => {
  it("measures adjacent five-column glyphs with one-column gaps", () => {
    expect(neededColumns("JOBERNEY")).toBe(47);
    expect(neededColumns("AB")).toBe(11);
  });

  it("includes three-column spaces and one gap per glyph pair", () => {
    expect(neededColumns("A B")).toBe(14);
    expect(neededColumns("A  B")).toBe(17);
  });

  it("normalizes case and edge whitespace without collapsing internal spaces", () => {
    expect(normalizeName("  bill   git  ")).toBe("BILL   GIT");
    expect(neededColumns("  bill   git  ")).toBe(50);
  });

  it("rejects unsupported glyphs", () => {
    expect(validateName("A-B")).toContain("A-Z");
    expect(validateName("   ")).toContain("Enter");
    expect(Boolean(normalizeName("   "))).toBe(false);
  });

  it("provides a conservative five-by-seven letter hint", () => {
    expect(approximateLetterHint(53)).toBe(9);
    expect(approximateLetterHint(47)).toBe(8);
  });
});
