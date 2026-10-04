import { request } from './client';

export interface SystemInfo {
  application_version: string;
  database_revision: string | null;
  application_mode: 'standalone' | 'edge' | 'cloud';
}
export const getSystemInfo = (signal?: AbortSignal) => request<SystemInfo>('/system/info', { signal });

export interface SystemDiagnostics extends SystemInfo {
  checked_at: string;
  database_status: 'OK' | 'ERROR' | 'UNKNOWN';
  database_latency_ms: number | null;
  sync_status: 'CONNECTED' | 'DISCONNECTED' | 'UNAVAILABLE' | 'DISABLED' | 'PAUSED' | 'DEGRADED' | 'UNKNOWN';
  last_sync_at: string | null;
  pending_sync_count: number | null;
  last_telemetry_at: string | null;
  telemetry_status: 'FRESH' | 'STALE' | 'DEGRADED' | 'UNAVAILABLE' | 'UNKNOWN';
  backup_status: 'AVAILABLE' | 'IN_PROGRESS' | 'FAILED' | 'NONE' | 'UNKNOWN';
  last_backup_at: string | null;
  disk_free_bytes: number | null;
  hostname: string | null;
  uptime_seconds: number | null;
}
export const getSystemDiagnostics = (signal?: AbortSignal) =>
  request<SystemDiagnostics>('/system/diagnostics', { signal });

export interface SystemRuntime {
  application_mode?: 'standalone' | 'edge' | 'cloud'; writes_enabled?: boolean; mode: 'disabled' | 'simulator' | 'modbus' | 'unknown'; alive: boolean; hostname: string | null; heartbeat_at: string | null }
export interface TransportStatus { detected_port?: string | null; detection_status?: string | null; detected_at?: string | null; detection_error?: string | null; redetect_pending?: boolean; connection_id: number; state: string; last_success: string | null; last_error: string | null; last_error_at: string | null; updated_at: string | null }
export interface DeviceStatus { device_id: number; state: string; last_success: string | null }
export interface TestResult { test_id: string | null; state: 'NOT_REQUESTED' | 'PENDING' | 'SUCCEEDED' | 'FAILED' | 'EXPIRED'; success: boolean | null; message: string | null; latency_ms: number | null }
export interface SerialAdapter { device: string; description: string; vid?: number | null; pid?: number | null; serial_number?: string | null; hwid?: string | null; manufacturer?: string | null; product?: string | null }
export interface SerialPorts { worker_host: string; observed_at: string; ports: SerialAdapter[]; error: string | null }
export const testConnection = (id: number, signal?: AbortSignal) => request<TestResult>(`/connections/${id}/test`, { method: 'POST', signal });
export const getTest = (id: number, signal?: AbortSignal) => request<TestResult>(`/connections/${id}/test`, { signal });
export const discoverSerial = () => request<SerialPorts>('/system/serial-ports');

export const redetectConnection = (id: number) => request<{ request_id: string; state: string }>(`/connections/${id}/redetect`, { method: 'POST' });
