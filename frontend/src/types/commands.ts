export const commandStatuses = ['QUEUED', 'EXECUTING', 'VERIFYING', 'SUCCESS', 'FAILED', 'CANCELLED', 'EXPIRED'] as const;
export type CommandStatus = typeof commandStatuses[number];
export interface Command {
  requested_by?: number | null; requested_by_username?: string | null;
  id: number; request_id: string; tag_id: number; tag_name: string; device_id: number; device_name: string;
  requested_value: string | boolean; previous_value: string | boolean | null; verified_value: string | boolean | null;
  status: CommandStatus; source: 'manual' | 'automation' | 'system'; telemetry_mode: 'simulator' | 'modbus';
  attempt_count: number; revision: number; created_at: string; expires_at: string;
  started_at: string | null; completed_at: string | null; error_message: string | null;
}
export function isCommand(value: unknown): value is Command {
  if (typeof value !== 'object' || value === null) return false;
  const row = value as Record<string, unknown>;
  return Number.isInteger(row.id) && Number(row.id) > 0 && Number.isInteger(row.tag_id)
    && Number.isInteger(row.device_id) && Number.isInteger(row.revision) && Number(row.revision) > 0
    && commandStatuses.includes(row.status as CommandStatus)
    && ['manual', 'automation', 'system'].includes(String(row.source))
    && ['simulator', 'modbus'].includes(String(row.telemetry_mode))
    && ['request_id', 'tag_name', 'device_name', 'created_at', 'expires_at'].every((key) => typeof row[key] === 'string')
    && (typeof row.requested_value === 'boolean' || typeof row.requested_value === 'string')
    && ['previous_value', 'verified_value'].every((key) => row[key] === null || typeof row[key] === 'boolean' || typeof row[key] === 'string')
    && ['started_at', 'completed_at', 'error_message'].every((key) => row[key] === null || typeof row[key] === 'string')
    && Number.isInteger(row.attempt_count);
}
export const commandValue = (value: Command['verified_value']) => value === null ? 'Not available' : typeof value === 'boolean' ? (value ? 'ON' : 'OFF') : value.replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1');
export const activeCommand = (command?: Command) => !!command && ['QUEUED', 'EXECUTING', 'VERIFYING'].includes(command.status);
