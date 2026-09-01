export type Theme = "light" | "dark";

export type ApiWarning =
  | string
  | {
      code?: string;
      detail?: string;
      message?: string;
    };

export interface AnalyzeResponse {
  job_id: string;
  rows: number;
  cols: number;
  theme: Theme;
  levels: number;
  palette: Record<string, string>;
  absent_count: number;
  preview_original_url: string;
  preview_overlay_url: string;
  max_name_columns: number;
  warnings?: ApiWarning[];
}

export interface RenderRequest {
  job_id: string;
  name: string;
  primary: string;
  secondary: string;
  outline: string;
  boldness: number;
  start: number | null;
}

export interface RenderResponse {
  fit: boolean;
  needed_cols: number;
  start: number;
  letter_cells: number;
  overlap_cells: number;
  empty_letter_cells: number;
  render_url: string;
  warnings?: ApiWarning[];
}

export type PreviewMode = "final" | "original" | "overlay";
