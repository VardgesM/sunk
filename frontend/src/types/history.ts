import type { Quality } from './telemetry';

export interface HistoryPoint {
  source?: string | null;
  recorded_at: string; source_timestamp: string | null;
  value_numeric: number | null; value_numeric_exact: string | null;
  value_boolean: boolean | null; value_text: string | null;
  quality: Quality; minimum: number | null; maximum: number | null; average: number | null;
  first_timestamp: string; last_timestamp: string; sample_count: number; has_invalid: boolean;
}
export interface HistoryResponse {
  tag: { id: number; key: string; name: string; unit: string | null; data_type: string };
  from_timestamp: string; to_timestamp: string; count: number; total_count: number;
  downsampled: boolean; truncated: boolean; points: HistoryPoint[];
}
