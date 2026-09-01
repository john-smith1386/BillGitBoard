import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
} from "react";
import {
  ApiError,
  analyzeImage,
  downloadGrid,
  mediaUrl,
  renderCalendar,
} from "./api";
import {
  builtBy,
  hasFooterLinks,
  otherProjects,
  otherProjectsLabel,
  supportLink,
  type SiteLink,
} from "./siteLinks";
import {
  MAX_NAME_LENGTH,
  approximateLetterHint,
  neededColumns,
  normalizeName,
  validateName,
} from "./fontMetrics";
import type {
  AnalyzeResponse,
  ApiWarning,
  PreviewMode,
  RenderResponse,
} from "./types";

const MAX_FILE_BYTES = 15 * 1024 * 1024;
const MIN_IMAGE_WIDTH = 200;
const MIN_IMAGE_HEIGHT = 80;
const ACCEPTED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const HEX_PATTERN = /^#[0-9A-F]{6}$/i;

type AnalysisPhase = "idle" | "validating" | "analyzing" | "ready" | "error";
type RenderPhase = "idle" | "rendering" | "ready" | "error";
type StartMode = "auto" | "manual";
type DownloadTarget = "png" | "json" | null;

interface ErrorData {
  code?: string;
  cols?: number;
  needed_cols?: number;
  detail?: unknown;
}

function Icon({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
    >
      {children}
    </svg>
  );
}

function UploadIcon() {
  return (
    <Icon size={24}>
      <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
      <path d="M5 14.5v3A2.5 2.5 0 007.5 20h9a2.5 2.5 0 002.5-2.5v-3" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </Icon>
  );
}

function DownloadIcon() {
  return (
    <Icon>
      <path d="M12 4v11m0 0l-4-4m4 4l4-4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
      <path d="M5 19h14" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </Icon>
  );
}

function RefreshIcon() {
  return (
    <Icon>
      <path d="M20 7v5h-5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
      <path d="M18.1 16a7 7 0 10.7-7.1L20 12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
    </Icon>
  );
}

function GridIcon() {
  return (
    <Icon>
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="3" y="3" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="10" y="3" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="17" y="3" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="3" y="10" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="10" y="10" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="17" y="10" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="3" y="17" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="10" y="17" />
      <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.6" width="5" x="17" y="17" />
    </Icon>
  );
}

function AlertIcon() {
  return (
    <Icon>
      <path d="M12 8v4m0 4h.01" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
      <path d="M10.2 4.9L3.1 17.1A2 2 0 004.8 20h14.4a2 2 0 001.7-2.9L13.8 4.9a2 2 0 00-3.6 0z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" />
    </Icon>
  );
}

function CheckIcon() {
  return (
    <Icon size={18}>
      <path d="M5 12.5l4 4L19 6.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
    </Icon>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getImageDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(file);

    image.onload = () => {
      const dimensions = { width: image.naturalWidth, height: image.naturalHeight };
      URL.revokeObjectURL(url);
      resolve(dimensions);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("The image could not be decoded."));
    };
    image.src = url;
  });
}

async function validateImageFile(file: File): Promise<void> {
  if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
    throw new Error("Choose a PNG, JPEG, or WebP image.");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("That image is larger than 15 MB. Choose a smaller file.");
  }
  if (file.size === 0) {
    throw new Error("That file is empty. Choose a valid screenshot.");
  }

  const { width, height } = await getImageDimensions(file);
  if (width < MIN_IMAGE_WIDTH || height < MIN_IMAGE_HEIGHT) {
    throw new Error(
      `The screenshot must be at least ${MIN_IMAGE_WIDTH} x ${MIN_IMAGE_HEIGHT} pixels.`,
    );
  }
}

function extractErrorData(error: ApiError): ErrorData {
  if (!error.payload || typeof error.payload !== "object") {
    return { code: error.code };
  }

  const payload = error.payload as Record<string, unknown>;
  const nested =
    payload.detail && typeof payload.detail === "object"
      ? (payload.detail as Record<string, unknown>)
      : payload;

  return {
    code:
      error.code ||
      (typeof nested.code === "string" ? nested.code : undefined) ||
      (typeof payload.code === "string" ? payload.code : undefined),
    cols: typeof nested.cols === "number" ? nested.cols : undefined,
    needed_cols:
      typeof nested.needed_cols === "number" ? nested.needed_cols : undefined,
    detail: nested.detail,
  };
}

function friendlyApiError(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : fallback;
  }

  const data = extractErrorData(error);
  switch (data.code) {
    case "NO_GRID":
    case "NOT_SEVEN_ROWS":
    case "GRID_UNRELIABLE":
      return "We could not find a reliable 7-row contribution grid. Crop closer to the calendar and try again.";
    case "NAME_TOO_LONG":
      return data.needed_cols && data.cols
        ? `This name needs ${data.needed_cols} columns, but the detected grid has ${data.cols}. Shorten the name.`
        : "This name is too wide for the detected grid. Shorten it and try again.";
    case "NAME_OVERFLOW":
      return "The name runs past the final week at that offset. Choose an earlier start week.";
    case "NAME_HITS_ABSENT_CELLS":
      return "The name crosses unavailable cells in a partial week. Try a different start week or a shorter name.";
    case "INVALID_NAME":
      return "Use only A-Z, 0-9, and spaces in the name.";
    case "JOB_EXPIRED":
    case "JOB_NOT_FOUND":
      return "This temporary job is no longer available. Upload the screenshot again to continue.";
    case "RATE_LIMITED":
      return "The analyze limit has been reached for this connection. Please try again later.";
    case "RENDER_RATE_LIMITED":
      return "The render limit has been reached for this connection. Please try again later.";
    case "RENDER_VARIANT_LIMIT":
      return "This upload has reached its distinct render limit. Upload the screenshot again to start a fresh job.";
    case "STORE_QUOTA_EXCEEDED":
      return "Temporary storage is full. Please try again after older jobs expire.";
    case "REQUEST_TOO_LARGE":
    case "FILE_TOO_LARGE":
      return "That upload is too large. The file limit is 15 MB.";
    case "NETWORK_ERROR":
      return error.message;
    default:
      if (error.status === 413) return "That upload is too large. The limit is 15 MB.";
      if (error.status === 429) {
        return "Too many requests have been made recently. Please try again later.";
      }
      return error.message || fallback;
  }
}

function warningText(warning: ApiWarning): string {
  if (typeof warning === "string") {
    if (warning === "PARTIAL_GRID") {
      return "Some cells are missing from the grid. Lettering will use only cells that exist.";
    }
    if (warning === "BLURRY") {
      return "The screenshot is compressed or blurry. Check the detected overlay before rendering.";
    }
    if (warning === "NOT_ENOUGH_COLORS") {
      return "Only two shade levels could be inferred, so the result may have less tonal detail.";
    }
    return warning.replaceAll("_", " ").toLowerCase();
  }

  if (warning.message) return warning.message;
  if (warning.detail) return warning.detail;
  if (warning.code) return warningText(warning.code);
  return "The service returned a warning for this image.";
}

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 1_000);
}

function ColorField({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const valid = HEX_PATTERN.test(value);
  return (
    <div className="color-field">
      <div className="field-label-row">
        <label htmlFor={`${id}-text`}>{label}</label>
        <span>{hint}</span>
      </div>
      <div className={`color-control${valid ? "" : " is-invalid"}`}>
        <label className="color-swatch" htmlFor={`${id}-picker`}>
          <span className="sr-only">Choose {label.toLowerCase()}</span>
          <input
            aria-label={`Choose ${label.toLowerCase()}`}
            id={`${id}-picker`}
            onChange={(event) => onChange(event.target.value.toUpperCase())}
            type="color"
            value={valid ? value : "#000000"}
          />
        </label>
        <input
          aria-describedby={`${id}-hint`}
          aria-invalid={!valid}
          id={`${id}-text`}
          maxLength={7}
          onChange={(event) => onChange(event.target.value.toUpperCase())}
          spellCheck={false}
          type="text"
          value={value}
        />
      </div>
      <p className={`field-hint${valid ? "" : " field-error"}`} id={`${id}-hint`}>
        {valid ? hint : "Enter a six-digit hex color, such as #163951."}
      </p>
    </div>
  );
}

function StatusCallout({ tone, children }: { tone: "error" | "warning" | "success"; children: ReactNode }) {
  return (
    <div className={`status-callout ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span className="status-callout-icon">
        {tone === "success" ? <CheckIcon /> : <AlertIcon />}
      </span>
      <div>{children}</div>
    </div>
  );
}

function EmptyPreview() {
  return (
    <div className="empty-preview">
      <div aria-hidden="true" className="demo-grid">
        {Array.from({ length: 126 }, (_, index) => (
          <span
            className={
              index % 23 === 0 || index % 19 === 4
                ? "level-3"
                : index % 13 === 0 || index % 17 === 2
                  ? "level-2"
                  : index % 7 === 3
                    ? "level-1"
                    : ""
            }
            key={index}
          />
        ))}
      </div>
      <div className="empty-preview-copy">
        <span className="empty-preview-icon"><GridIcon /></span>
        <h3>Your calendar will appear here</h3>
        <p>Upload a clear screenshot of a GitHub-style contribution grid to begin.</p>
      </div>
    </div>
  );
}

function FooterLink({
  link,
  variant = "pill",
}: {
  link: SiteLink;
  variant?: "pill" | "inline" | "support";
}) {
  const [logoFailed, setLogoFailed] = useState(false);

  return (
    <a
      className={`footer-link footer-link-${variant}`}
      href={link.href}
      rel="noopener noreferrer"
      target="_blank"
    >
      {link.logo && !logoFailed && (
        <img
          alt=""
          aria-hidden="true"
          className="footer-link-logo"
          loading="lazy"
          onError={() => setLogoFailed(true)}
          src={link.logo}
        />
      )}
      <span>{link.label}</span>
    </a>
  );
}

function App() {
  const fileInputId = useId();
  const nameInputRef = useRef<HTMLInputElement>(null);
  const analyzeAbortRef = useRef<AbortController | null>(null);
  const renderAbortRef = useRef<AbortController | null>(null);
  const successfulRenderKeyRef = useRef<string | null>(null);
  const activeRenderKeyRef = useRef<string | null>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [localPreviewUrl, setLocalPreviewUrl] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [analysisPhase, setAnalysisPhase] = useState<AnalysisPhase>("idle");
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [primary, setPrimary] = useState("#163951");
  const [secondary, setSecondary] = useState("#F5A623");
  const [outline, setOutline] = useState("#0A1620");
  const [boldness, setBoldness] = useState(2);
  const [startMode, setStartMode] = useState<StartMode>("auto");
  const [manualStart, setManualStart] = useState(0);
  const [livePreview, setLivePreview] = useState(true);

  const [renderPhase, setRenderPhase] = useState<RenderPhase>("idle");
  const [renderResult, setRenderResult] = useState<RenderResponse | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [previewMode, setPreviewMode] = useState<PreviewMode>("final");
  const [downloadTarget, setDownloadTarget] = useState<DownloadTarget>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      analyzeAbortRef.current?.abort();
      renderAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    return () => {
      if (localPreviewUrl) URL.revokeObjectURL(localPreviewUrl);
    };
  }, [localPreviewUrl]);

  const normalizedName = useMemo(() => normalizeName(name), [name]);
  const requiredColumns = useMemo(() => neededColumns(name), [name]);
  const maxStart = analysis
    ? Math.max(0, analysis.cols - Math.max(1, requiredColumns))
    : 0;
  const centeredStart = analysis
    ? Math.max(0, Math.floor((analysis.cols - requiredColumns) / 2))
    : 0;

  useEffect(() => {
    setManualStart((current) => Math.min(Math.max(0, current), maxStart));
  }, [maxStart]);

  const localNameError = nameTouched || name ? validateName(name) : null;
  const fitError =
    analysis && !localNameError && requiredColumns > analysis.cols
      ? `${normalizedName} needs ${requiredColumns} columns. This grid has ${analysis.cols}. Shorten it to about ${approximateLetterHint(analysis.cols)} letters.`
      : null;
  const manualStartError =
    analysis && startMode === "manual" && manualStart + requiredColumns > analysis.cols
      ? `Start at week ${maxStart} or earlier so the name remains inside the grid.`
      : null;
  const colorsValid = [primary, secondary, outline].every((color) => HEX_PATTERN.test(color));
  const canRender = Boolean(
    analysis &&
      analysisPhase === "ready" &&
      normalizedName &&
      !localNameError &&
      !fitError &&
      !manualStartError &&
      colorsValid,
  );

  const renderKey = canRender && analysis
    ? JSON.stringify({
        job: analysis.job_id,
        name: normalizedName,
        primary: primary.toUpperCase(),
        secondary: secondary.toUpperCase(),
        outline: outline.toUpperCase(),
        boldness,
        start: startMode === "auto" ? null : manualStart,
      })
    : null;

  const previewStale = Boolean(
    renderResult && renderKey !== successfulRenderKeyRef.current,
  );

  const beginAnalysis = useCallback(async (file: File) => {
    analyzeAbortRef.current?.abort();
    renderAbortRef.current?.abort();
    const controller = new AbortController();
    analyzeAbortRef.current = controller;

    setSelectedFile(file);
    setLocalPreviewUrl(URL.createObjectURL(file));
    setAnalysis(null);
    setRenderResult(null);
    successfulRenderKeyRef.current = null;
    activeRenderKeyRef.current = null;
    setAnalysisError(null);
    setRenderError(null);
    setDownloadError(null);
    setAnalysisPhase("validating");
    setRenderPhase("idle");
    setPreviewMode("final");

    try {
      await validateImageFile(file);
      if (controller.signal.aborted) return;

      setAnalysisPhase("analyzing");
      const result = await analyzeImage(file, controller.signal);
      if (controller.signal.aborted) return;

      if (!result.job_id || result.rows !== 7 || !Number.isFinite(result.cols)) {
        throw new Error("The service returned an incomplete grid analysis. Please try again.");
      }

      setAnalysis(result);
      setAnalysisPhase("ready");
      window.setTimeout(() => nameInputRef.current?.focus(), 80);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setAnalysisPhase("error");
      setAnalysisError(friendlyApiError(error, "The calendar could not be analyzed."));
    }
  }, []);

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void beginAnalysis(file);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void beginAnalysis(file);
  };

  const performRender = useCallback(async () => {
    if (!analysis || !canRender || !renderKey) return;
    if (renderKey === successfulRenderKeyRef.current) return;
    if (renderKey === activeRenderKeyRef.current) return;

    renderAbortRef.current?.abort();
    const controller = new AbortController();
    renderAbortRef.current = controller;
    activeRenderKeyRef.current = renderKey;
    setRenderPhase("rendering");
    setRenderError(null);
    setDownloadError(null);

    try {
      const result = await renderCalendar(
        {
          job_id: analysis.job_id,
          name: normalizedName,
          primary: primary.toUpperCase(),
          secondary: secondary.toUpperCase(),
          outline: outline.toUpperCase(),
          boldness,
          start: startMode === "auto" ? null : manualStart,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;

      successfulRenderKeyRef.current = renderKey;
      setRenderResult(result);
      setRenderPhase("ready");
      setPreviewMode("final");
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setRenderPhase("error");
      setRenderError(friendlyApiError(error, "The calendar could not be rendered."));
    } finally {
      if (activeRenderKeyRef.current === renderKey) {
        activeRenderKeyRef.current = null;
      }
    }
  }, [
    analysis,
    boldness,
    canRender,
    manualStart,
    normalizedName,
    outline,
    primary,
    renderKey,
    secondary,
    startMode,
  ]);

  useEffect(() => {
    if (!livePreview || !canRender || !renderKey) return;
    if (renderKey === successfulRenderKeyRef.current) return;

    const timeout = window.setTimeout(() => {
      void performRender();
    }, 550);
    return () => window.clearTimeout(timeout);
  }, [canRender, livePreview, performRender, renderKey]);

  const savePng = async () => {
    if (!renderResult) return;
    setDownloadTarget("png");
    setDownloadError(null);
    try {
      const response = await fetch(mediaUrl(renderResult.render_url));
      if (!response.ok) throw new Error("The rendered PNG is no longer available.");
      const blob = await response.blob();
      const stem = normalizedName.toLowerCase().replace(/\s+/g, "-") || "contribution-overlay";
      downloadBlob(blob, `${stem}.png`);
    } catch (error) {
      setDownloadError(friendlyApiError(error, "The PNG could not be downloaded."));
    } finally {
      setDownloadTarget(null);
    }
  };

  const saveGrid = async () => {
    if (!analysis) return;
    setDownloadTarget("json");
    setDownloadError(null);
    try {
      const blob = await downloadGrid(analysis.job_id);
      downloadBlob(blob, `billgitboard-${analysis.job_id}-grid.json`);
    } catch (error) {
      setDownloadError(friendlyApiError(error, "The debug grid could not be downloaded."));
    } finally {
      setDownloadTarget(null);
    }
  };

  const currentImageUrl = useMemo(() => {
    if (!analysis) return localPreviewUrl;
    if (previewMode === "original") {
      return analysis.preview_original_url
        ? mediaUrl(analysis.preview_original_url)
        : localPreviewUrl;
    }
    if (previewMode === "overlay") {
      return analysis.preview_overlay_url
        ? mediaUrl(analysis.preview_overlay_url)
        : localPreviewUrl;
    }
    if (renderResult?.render_url) return mediaUrl(renderResult.render_url);
    return analysis.preview_original_url
      ? mediaUrl(analysis.preview_original_url)
      : localPreviewUrl;
  }, [analysis, localPreviewUrl, previewMode, renderResult]);

  const warnings = useMemo(
    () => [...(analysis?.warnings || []), ...(renderResult?.warnings || [])],
    [analysis, renderResult],
  );

  const fitPercent = analysis
    ? Math.min(100, Math.round((requiredColumns / analysis.cols) * 100))
    : 0;
  const spareColumns = analysis ? analysis.cols - requiredColumns : 0;
  const isAnalyzing = analysisPhase === "validating" || analysisPhase === "analyzing";
  const noFinalPreview = previewMode === "final" && !renderResult;

  return (
    <div className="app-shell">
      <header className="site-header">
        <a aria-label="BillGitBoard home" className="brand" href="/">
          <span aria-hidden="true" className="brand-mark">
            <span /><span /><span /><span /><span /><span /><span /><span /><span />
          </span>
          <span>BillGitBoard</span>
        </a>
        <div className="header-note">
          <span aria-hidden="true" className="status-dot" />
          No GitHub login required
        </div>
      </header>

      <main>
        <div aria-live="polite" className="sr-only">
          {analysisPhase === "validating" && "Validating screenshot."}
          {analysisPhase === "analyzing" && "Analyzing contribution grid."}
          {analysisPhase === "ready" && analysis && `Detected a 7 row by ${analysis.cols} column grid.`}
          {renderPhase === "rendering" && "Rendering preview."}
          {renderPhase === "ready" && renderResult && "Preview updated."}
        </div>
        <section className="hero">
          <div>
            <p className="eyebrow"><span /> Contribution calendar lettering</p>
            <h1>Make your mark, <em>one cell at a time.</em></h1>
            <p className="hero-copy">
              Upload a contribution-calendar screenshot. BillGitBoard learns its real grid and
              palette, then sets your name without changing the surrounding cells.
            </p>
          </div>
          <ol aria-label="How it works" className="step-list">
            <li><span>1</span><strong>Upload</strong><small>Your screenshot</small></li>
            <li><span>2</span><strong>Customize</strong><small>Name and color</small></li>
            <li><span>3</span><strong>Download</strong><small>Crisp PNG</small></li>
          </ol>
        </section>

        <div className="workspace">
          <div className="editor-column">
            <section className="panel upload-panel" aria-labelledby="upload-heading">
              <div className="section-heading">
                <span className="section-number">01</span>
                <div>
                  <h2 id="upload-heading">Add your calendar</h2>
                  <p>A close crop works best. Labels and the contribution legend are okay.</p>
                </div>
              </div>

              <div
                className={`drop-zone${dragActive ? " is-dragging" : ""}${isAnalyzing ? " is-busy" : ""}`}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                    setDragActive(false);
                  }
                }}
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleDrop}
              >
                <input
                  accept="image/png,image/jpeg,image/webp"
                  className="sr-only"
                  disabled={isAnalyzing}
                  id={fileInputId}
                  onChange={handleFileInput}
                  type="file"
                />
                <label className="drop-zone-action" htmlFor={fileInputId}>
                  <span className="upload-icon"><UploadIcon /></span>
                  <span className="drop-zone-copy">
                    <strong>
                      {selectedFile
                        ? isAnalyzing
                          ? analysisPhase === "validating"
                            ? "Checking image..."
                            : "Finding the 7-row grid..."
                          : "Replace screenshot"
                        : "Drop your screenshot here"}
                    </strong>
                    <span>{selectedFile ? selectedFile.name : "or choose a file from your device"}</span>
                  </span>
                  <span className="browse-button">{selectedFile ? "Choose another" : "Browse files"}</span>
                </label>
                <div className="drop-zone-meta">
                  <span>PNG, JPEG, or WebP</span>
                  <span aria-hidden="true">•</span>
                  <span>15 MB max</span>
                  {selectedFile && (
                    <>
                      <span aria-hidden="true">•</span>
                      <span>{formatBytes(selectedFile.size)}</span>
                    </>
                  )}
                </div>
                {isAnalyzing && <span aria-hidden="true" className="drop-progress" />}
              </div>

              {analysisError && <StatusCallout tone="error">{analysisError}</StatusCallout>}
              {analysis && analysisPhase === "ready" && (
                <StatusCallout tone="success">
                  Grid found: {analysis.rows} rows by {analysis.cols} weeks, with {analysis.levels} shade levels.
                </StatusCallout>
              )}
            </section>

            <section
              aria-labelledby="lettering-heading"
              aria-disabled={!analysis}
              className={`panel controls-panel${analysis ? "" : " is-disabled"}`}
            >
              <div className="section-heading">
                <span className="section-number">02</span>
                <div>
                  <h2 id="lettering-heading">Set your lettering</h2>
                  <p>Only real cells in the detected grid can be used.</p>
                </div>
              </div>

              <fieldset disabled={!analysis}>
                <div className="name-field">
                  <div className="field-label-row">
                    <label htmlFor="name">Name</label>
                    <span>{normalizedName.length} / {MAX_NAME_LENGTH}</span>
                  </div>
                  <input
                    aria-describedby="name-help name-fit"
                    aria-invalid={Boolean(localNameError || fitError)}
                    autoComplete="off"
                    id="name"
                    onBlur={() => setNameTouched(true)}
                    onChange={(event) => {
                      setName(event.target.value.toUpperCase());
                      setNameTouched(true);
                    }}
                    placeholder="e.g. JOBERNEY"
                    ref={nameInputRef}
                    spellCheck={false}
                    type="text"
                    value={name}
                  />
                  <p className="field-hint" id="name-help">
                    A-Z, 0-9, and spaces. Each glyph is exactly 5 x 7 cells; spaces use 3 columns.
                  </p>
                </div>

                {analysis && (
                  <div
                    className={`fit-meter${fitError || localNameError ? " is-error" : requiredColumns ? " is-valid" : ""}`}
                    id="name-fit"
                  >
                    <div className="fit-meter-row">
                      <span>
                        {requiredColumns
                          ? `${requiredColumns} of ${analysis.cols} columns`
                          : `0 of ${analysis.cols} columns`}
                      </span>
                      <strong>
                        {localNameError
                          ? localNameError
                          : fitError
                            ? "Does not fit"
                            : requiredColumns
                              ? `${spareColumns} spare`
                              : "Enter a name"}
                      </strong>
                    </div>
                    <span className="fit-track">
                      <span style={{ width: `${fitPercent}%` }} />
                    </span>
                    {fitError && <p>{fitError}</p>}
                  </div>
                )}

                <div className="control-divider" />

                <div className="color-grid">
                  <ColorField
                    hint="Existing contributions"
                    id="primary"
                    label="Primary color"
                    onChange={setPrimary}
                    value={primary}
                  />
                  <ColorField
                    hint="Empty letter cells"
                    id="secondary"
                    label="Secondary color"
                    onChange={setSecondary}
                    value={secondary}
                  />
                </div>

                <div className="control-divider" />

                <div className="range-control">
                  <div className="field-label-row">
                    <div>
                      <label htmlFor="boldness">Outline boldness</label>
                      <p>Strokes each letter as one connected shape.</p>
                    </div>
                    <output htmlFor="boldness">{boldness} px</output>
                  </div>
                  <input
                    id="boldness"
                    max="8"
                    min="0"
                    onChange={(event) => setBoldness(Number(event.target.value))}
                    step="1"
                    type="range"
                    value={boldness}
                  />
                  <div aria-hidden="true" className="range-labels"><span>None</span><span>Bold</span></div>
                </div>

                <ColorField
                  hint="Auto default: dark neutral"
                  id="outline"
                  label="Outline color"
                  onChange={setOutline}
                  value={outline}
                />

                <div className="control-divider" />

                <div className="placement-control">
                  <div className="field-label-row">
                    <div>
                      <span className="label-text">Start position</span>
                      <p>Place the full word, measured in calendar weeks.</p>
                    </div>
                  </div>
                  <div aria-label="Start position" className="choice-cards" role="radiogroup">
                    <label className={startMode === "auto" ? "is-selected" : ""}>
                      <input
                        checked={startMode === "auto"}
                        name="start-mode"
                        onChange={() => setStartMode("auto")}
                        type="radio"
                      />
                      <span><strong>Auto-center</strong><small>Starts at week {centeredStart}</small></span>
                      <i><CheckIcon /></i>
                    </label>
                    <label className={startMode === "manual" ? "is-selected" : ""}>
                      <input
                        checked={startMode === "manual"}
                        name="start-mode"
                        onChange={() => setStartMode("manual")}
                        type="radio"
                      />
                      <span><strong>Manual offset</strong><small>Choose the starting week</small></span>
                      <i><CheckIcon /></i>
                    </label>
                  </div>

                  {startMode === "manual" && (
                    <div className="manual-offset">
                      <div className="offset-value-row">
                        <label htmlFor="start-offset">Starting week</label>
                        <div className="number-input-wrap">
                          <input
                            aria-label="Starting week number"
                            aria-describedby="offset-help"
                            id="start-offset-number"
                            max={maxStart}
                            min="0"
                            onChange={(event) => {
                              const next = Number(event.target.value);
                              setManualStart(Math.min(maxStart, Math.max(0, Number.isFinite(next) ? next : 0)));
                            }}
                            type="number"
                            value={manualStart}
                          />
                          <span>week</span>
                        </div>
                      </div>
                      <input
                        aria-label="Starting week offset"
                        id="start-offset"
                        max={maxStart}
                        min="0"
                        onChange={(event) => setManualStart(Number(event.target.value))}
                        step="1"
                        type="range"
                        value={manualStart}
                      />
                      <p className="field-hint" id="offset-help">Available range: 0 to {maxStart}.</p>
                      {manualStartError && <p className="field-error">{manualStartError}</p>}
                    </div>
                  )}
                </div>

                <div className="render-controls">
                  <label className="switch-row">
                    <span><strong>Live preview</strong><small>Updates 550 ms after you stop editing</small></span>
                    <input
                      checked={livePreview}
                      onChange={(event) => setLivePreview(event.target.checked)}
                      role="switch"
                      type="checkbox"
                    />
                  </label>
                  <button
                    className="button button-primary render-button"
                    disabled={!canRender || renderPhase === "rendering" || renderKey === successfulRenderKeyRef.current}
                    onClick={() => void performRender()}
                    type="button"
                  >
                    {renderPhase === "rendering" ? <span className="button-spinner" /> : <RefreshIcon />}
                    {renderPhase === "rendering"
                      ? "Rendering..."
                      : renderResult
                        ? previewStale
                          ? "Update preview"
                          : "Preview up to date"
                        : "Render preview"}
                  </button>
                </div>
              </fieldset>

              {renderError && <StatusCallout tone="error">{renderError}</StatusCallout>}
            </section>
          </div>

          <section className="panel preview-panel" aria-labelledby="preview-heading">
            <div className="preview-header">
              <div>
                <p className="preview-kicker">Output</p>
                <h2 id="preview-heading">Calendar preview</h2>
              </div>
              {analysis && (
                <div aria-label="Preview view" className="preview-tabs" role="radiogroup">
                  {([
                    ["final", "Final"],
                    ["original", "Original"],
                    ["overlay", "Detection"],
                  ] as const).map(([value, label]) => (
                    <label className={previewMode === value ? "is-selected" : ""} key={value}>
                      <input
                        checked={previewMode === value}
                        name="preview-mode"
                        onChange={() => setPreviewMode(value)}
                        type="radio"
                      />
                      {label}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div
              aria-busy={isAnalyzing || renderPhase === "rendering"}
              className={`preview-stage${currentImageUrl ? " has-image" : ""}${noFinalPreview ? " needs-render" : ""}`}
            >
              {!currentImageUrl ? (
                <EmptyPreview />
              ) : (
                <>
                  <img
                    alt={
                      previewMode === "overlay"
                        ? "Detected contribution grid overlay"
                        : previewMode === "original"
                          ? "Original uploaded contribution calendar"
                          : renderResult
                            ? `Rendered contribution calendar spelling ${normalizedName}`
                            : "Uploaded contribution calendar"
                    }
                    src={currentImageUrl}
                  />
                  {isAnalyzing && (
                    <div className="preview-scrim">
                      <span className="scan-loader"><i /></span>
                      <strong>{analysisPhase === "validating" ? "Checking image" : "Mapping the grid"}</strong>
                      <small>{analysisPhase === "validating" ? "Validating format and dimensions" : "Finding cells and learning the palette"}</small>
                    </div>
                  )}
                  {noFinalPreview && !isAnalyzing && (
                    <div className="preview-scrim soft">
                      {renderPhase === "rendering" ? (
                        <>
                          <span className="button-spinner dark" />
                          <strong>Building your lettering</strong>
                          <small>Preserving every non-letter cell</small>
                        </>
                      ) : (
                        <>
                          <span className="empty-preview-icon"><GridIcon /></span>
                          <strong>{analysis ? "Your grid is ready" : "Choose a screenshot"}</strong>
                          <small>{analysis ? "Enter a name to create the final preview" : "PNG, JPEG, or WebP up to 15 MB"}</small>
                        </>
                      )}
                    </div>
                  )}
                  {renderPhase === "rendering" && renderResult && previewMode === "final" && (
                    <div className="rendering-badge"><span className="button-spinner dark" /> Updating preview</div>
                  )}
                </>
              )}
            </div>

            {analysis ? (
              <div className="analysis-summary">
                <div className="stat-grid">
                  <div><span>Grid</span><strong>{analysis.rows} x {analysis.cols}</strong><small>rows x weeks</small></div>
                  <div><span>Theme</span><strong className="capitalize">{analysis.theme}</strong><small>detected</small></div>
                  <div><span>Shades</span><strong>{analysis.levels}</strong><small>palette levels</small></div>
                  <div><span>Unavailable</span><strong>{analysis.absent_count}</strong><small>partial cells</small></div>
                </div>

                <div className="palette-row">
                  <div><span>Detected palette</span><small>Level 0 to {Math.max(0, analysis.levels - 1)}</small></div>
                  <ol aria-label="Detected color palette">
                    {Object.entries(analysis.palette)
                      .sort(([a], [b]) => Number(a) - Number(b))
                      .map(([level, color]) => (
                        <li key={level} title={`Level ${level}: ${color}`}>
                          <span style={{ backgroundColor: color }} />
                          <small>{level}</small>
                        </li>
                      ))}
                  </ol>
                </div>

                {renderResult && (
                  <div className="render-summary">
                    <span><strong>{renderResult.letter_cells}</strong> letter cells</span>
                    <span><strong>{renderResult.overlap_cells}</strong> overlap recolors</span>
                    <span><strong>{renderResult.empty_letter_cells}</strong> empty fills</span>
                    <span><strong>Week {renderResult.start}</strong> start</span>
                  </div>
                )}

                {warnings.map((warning, index) => (
                  <StatusCallout key={`${warningText(warning)}-${index}`} tone="warning">
                    {warningText(warning)}
                  </StatusCallout>
                ))}
              </div>
            ) : (
              <div className="analysis-placeholder">
                <span><i /> Grid dimensions</span>
                <span><i /> Shade palette</span>
                <span><i /> Cell availability</span>
              </div>
            )}

            <div className="download-bar">
              <div>
                <strong>Ready to keep it?</strong>
                <span>PNG is rebuilt at a crisp, consistent scale.</span>
              </div>
              <div className="download-actions">
                <button
                  className="button button-secondary"
                  disabled={!analysis || downloadTarget !== null}
                  onClick={() => void saveGrid()}
                  type="button"
                >
                  {downloadTarget === "json" ? <span className="button-spinner dark" /> : <GridIcon />}
                  Grid JSON
                </button>
                <button
                  className="button button-primary"
                  disabled={!renderResult || previewStale || downloadTarget !== null}
                  onClick={() => void savePng()}
                  type="button"
                >
                  {downloadTarget === "png" ? <span className="button-spinner" /> : <DownloadIcon />}
                  Download PNG
                </button>
              </div>
            </div>
            {previewStale && (
              <p className="stale-note" role="status">The controls changed. Update the preview before downloading.</p>
            )}
            {downloadError && <StatusCallout tone="error">{downloadError}</StatusCallout>}
          </section>
        </div>
      </main>

      <footer>
        <span>BillGitBoard</span>
        <span>Temporary jobs expire after 24 hours.</span>
        {hasFooterLinks && (
          <div className="footer-links">
            {supportLink && <FooterLink link={supportLink} variant="support" />}
            {otherProjects.length > 0 && (
              <>
                <span className="footer-links-label">{otherProjectsLabel}</span>
                {otherProjects.map((project) => (
                  <FooterLink key={project.href} link={project} />
                ))}
              </>
            )}
            {builtBy && (
              <span className="footer-built-by">
                Built by <FooterLink link={builtBy} variant="inline" />
              </span>
            )}
          </div>
        )}
      </footer>
    </div>
  );
}

export default App;
