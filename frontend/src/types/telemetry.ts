import { isCommand, type Command } from './commands';
export const qualities = ['GOOD', 'STALE', 'BAD', 'COMM_ERROR', 'DISABLED'] as const;
export type Quality = typeof qualities[number];

export interface CurrentValue {
  tag_id: number; key: string; name: string; device_id: number; data_type: string;
  unit: string | null; enabled: boolean; effective_enabled: boolean;
  value_numeric: number | null; value_numeric_exact: string | null;
  value_boolean: boolean | null; value_text: string | null; raw_value: string | null;
  quality: Quality | null; source_timestamp: string | null; updated_at: string | null;
  error: string | null; revision: number;
  source?: 'simulator' | 'modbus_rtu' | 'modbus_tcp' | null;
}

export type LiveEvent =
  | { type: 'command_status'; data: Command }
  | { type: 'tag_value'; data: CurrentValue }
  | { type: 'tag_deleted'; tag_id: number }
  | { type: 'ready'; version: 1; listener_ready: boolean }
  | { type: 'stream_status'; ready: boolean }
  | { type: 'heartbeat'; listener_ready: boolean; timestamp: string }
  | { type: 'resync_required' };

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

export function isCurrentValue(value: unknown): value is CurrentValue {
  if (!object(value)) return false;
  return Number.isInteger(value.tag_id) && Number(value.tag_id) > 0 && Number.isInteger(value.device_id)
    && Number.isInteger(value.revision) && Number(value.revision) >= 0
    && typeof value.key === 'string' && typeof value.name === 'string' && typeof value.data_type === 'string'
    && typeof value.enabled === 'boolean' && typeof value.effective_enabled === 'boolean'
    && (value.value_numeric === null || typeof value.value_numeric === 'number' && Number.isFinite(value.value_numeric))
    && (value.value_boolean === null || typeof value.value_boolean === 'boolean')
    && (value.quality === null || qualities.includes(value.quality as Quality))
    && (value.source === undefined || value.source === null || ['simulator', 'modbus_rtu', 'modbus_tcp'].includes(String(value.source)))
    && ['unit', 'value_numeric_exact', 'value_text', 'raw_value', 'source_timestamp', 'updated_at', 'error']
      .every((key) => nullableString(value[key]));
}

export function parseLiveEvent(data: string): LiveEvent {
  const value: unknown = JSON.parse(data);
  if (!object(value)) throw new Error('Invalid live event');
  if (value.type === 'command_status' && isCommand(value.data)) return { type: 'command_status', data: value.data };
  if (value.type === 'tag_value' && isCurrentValue(value.data)) return { type: 'tag_value', data: value.data };
  if (value.type === 'tag_deleted' && Number.isInteger(value.tag_id) && Number(value.tag_id) > 0) return { type: 'tag_deleted', tag_id: Number(value.tag_id) };
  if (value.type === 'resync_required') return { type: 'resync_required' };
  if (value.type === 'ready' && value.version === 1 && typeof value.listener_ready === 'boolean') return { type: 'ready', version: 1, listener_ready: value.listener_ready };
  if (value.type === 'stream_status' && typeof value.ready === 'boolean') return { type: 'stream_status', ready: value.ready };
  if (value.type === 'heartbeat' && typeof value.listener_ready === 'boolean' && typeof value.timestamp === 'string') return { type: 'heartbeat', listener_ready: value.listener_ready, timestamp: value.timestamp };
  throw new Error('Unsupported live event');
}
