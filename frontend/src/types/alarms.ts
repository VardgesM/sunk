export type Severity = 'INFO' | 'WARNING' | 'CRITICAL';
export interface AlarmInput {
  name: string; description: string | null; tag_id: number;
  operator: '>' | '>=' | '<' | '<=' | '==' | '!='; value: string | boolean;
  severity: Severity; enabled: boolean; for_duration_ms: number | null;
  hysteresis: string; notification_enabled: boolean;
}
export interface AlarmRule extends AlarmInput { id: number; created_at: string; updated_at: string }
export interface AlarmEvent {
  acknowledged_by?: number | null; acknowledged_by_username?: string | null;
  id: number; rule_id: number; tag_id: number; name: string; tag_name: string;
  unit: string | null; condition: string; severity: Severity;
  state: 'ACTIVE' | 'ACKNOWLEDGED' | 'CLEARED'; value_numeric: string | null;
  value_boolean: boolean | null; activated_at: string; acknowledged_at: string | null;
  cleared_at: string | null; clear_reason: string | null; revision: number;
}
export interface Delivery { id: number; event_id: number | null; kind: string; status: string; attempt_count: number; created_at: string; completed_at: string | null; error: string | null }
export function isAlarmEvent(value: unknown): value is AlarmEvent {
  if (typeof value !== 'object' || value === null) return false;
  const row = value as Record<string, unknown>;
  return ['id', 'rule_id', 'tag_id', 'revision'].every(k => Number.isInteger(row[k]) && Number(row[k]) > 0)
    && ['name', 'tag_name', 'condition', 'activated_at'].every(k => typeof row[k] === 'string')
    && ['unit', 'value_numeric', 'acknowledged_at', 'cleared_at', 'clear_reason'].every(k => row[k] === null || typeof row[k] === 'string')
    && (row.value_boolean === null || typeof row.value_boolean === 'boolean')
    && ['INFO', 'WARNING', 'CRITICAL'].includes(String(row.severity))
    && ['ACTIVE', 'ACKNOWLEDGED', 'CLEARED'].includes(String(row.state));
}
