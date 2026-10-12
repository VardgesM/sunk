import type { AlarmEvent } from '../../types/alarms';

export const alarmTime = (value: string | null) => value ? new Date(value).toLocaleString() : 'Not recorded';

export function triggerValue(event: AlarmEvent): string {
  if (event.value_boolean !== null) return event.value_boolean ? 'ON' : 'OFF';
  return event.value_numeric === null ? 'Unavailable' : `${event.value_numeric}${event.unit ? ` ${event.unit}` : ''}`;
}

const severityOrder = { CRITICAL: 0, WARNING: 1, INFO: 2 };
// Only sort the loaded page. Server filtering and pagination remain authoritative.
export function orderOpenAlarms(events: AlarmEvent[]): AlarmEvent[] {
  return [...events].sort((a, b) => Number(a.state !== 'ACTIVE') - Number(b.state !== 'ACTIVE')
    || severityOrder[a.severity] - severityOrder[b.severity]
    || b.activated_at.localeCompare(a.activated_at) || b.id - a.id);
}
