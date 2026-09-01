export const MAX_NAME_LENGTH = 24;
export const NAME_PATTERN = /^[A-Z0-9 ]+$/;

export function normalizeName(value: string): string {
  return value.trim().toUpperCase();
}

export function neededColumns(value: string): number {
  const name = normalizeName(value);
  if (!name) return 0;

  const characters = Array.from(name);
  const glyphCount = characters.filter((character) => character !== " ").length;
  const spaceCount = characters.length - glyphCount;

  return 5 * glyphCount + Math.max(0, glyphCount - 1) + 3 * spaceCount;
}

export function validateName(value: string): string | null {
  const normalized = normalizeName(value);

  if (!normalized) return "Enter a name to render.";
  if (normalized.length > MAX_NAME_LENGTH) {
    return `Use ${MAX_NAME_LENGTH} characters or fewer.`;
  }
  if (!NAME_PATTERN.test(normalized)) {
    return "Use only A-Z, 0-9, and spaces.";
  }
  return null;
}

export function approximateLetterHint(cols: number): number {
  if (cols <= 0) return 0;
  return Math.max(1, Math.floor((cols + 1) / 6));
}
