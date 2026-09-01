import type { AnalyzeResponse, RenderRequest, RenderResponse } from "./types";

const configuredBase = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly payload?: unknown;

  constructor(message: string, status: number, code?: string, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${configuredBase}${normalizedPath}`;
}

export function mediaUrl(path: string): string {
  return apiUrl(path);
}

function getErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const record = payload as Record<string, unknown>;
  const detail = record.detail;

  if (typeof record.message === "string") return record.message;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    return getErrorMessage(detail, fallback);
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      })
      .join(" ");
  }
  return fallback;
}

async function readPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text ? { detail: text } : null;
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  fallbackError: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      "The service could not be reached. Check your connection and try again.",
      0,
      "NETWORK_ERROR",
      error,
    );
  }

  const payload = await readPayload(response);
  if (!response.ok) {
    const code =
      payload && typeof payload === "object" && "code" in payload
        ? String((payload as { code: unknown }).code)
        : undefined;
    throw new ApiError(getErrorMessage(payload, fallbackError), response.status, code, payload);
  }

  return payload as T;
}

export function analyzeImage(file: File, signal?: AbortSignal): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append("file", file);
  return requestJson<AnalyzeResponse>(
    "/api/analyze",
    { method: "POST", body: form, signal },
    "The calendar could not be analyzed.",
  );
}

export function renderCalendar(
  body: RenderRequest,
  signal?: AbortSignal,
): Promise<RenderResponse> {
  return requestJson<RenderResponse>(
    "/api/render",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    },
    "The calendar could not be rendered.",
  );
}

export async function downloadGrid(jobId: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/grid`), {
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    throw new ApiError(
      "The debug grid could not be downloaded. Check your connection and try again.",
      0,
      "NETWORK_ERROR",
      error,
    );
  }

  if (!response.ok) {
    const payload = await readPayload(response);
    const code =
      payload && typeof payload === "object" && "code" in payload
        ? String((payload as { code: unknown }).code)
        : undefined;
    throw new ApiError(
      getErrorMessage(payload, "The debug grid could not be downloaded."),
      response.status,
      code,
      payload,
    );
  }

  return response.blob();
}
