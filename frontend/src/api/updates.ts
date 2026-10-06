import { request } from './client';

export interface UpdateStatus {
  state: string;
  installed_version: string;
  channel: 'Stable';
  last_checked: string | null;
  release: { version: string; published_at: string; notes: string; manifest: { sha256: string; size: number } } | null;
  available: boolean;
  runner_available: boolean;
  install_supported: boolean;
  message: string | null;
  job_id: string | null;
  from_version: string | null;
  backup_id: string | null;
  failure_stage: string | null;
  error: string | null;
  recovery_required: boolean;
}

export const updatesApi = {
  status: (signal?: AbortSignal) => request<UpdateStatus>('/system/updates/status', { signal }),
  check: () => request<UpdateStatus>('/system/updates/check', { method: 'POST' }),
  install: (version: string, passphrase: string) => request<UpdateStatus>('/system/updates/install', {
    method: 'POST', body: JSON.stringify({ version, passphrase, confirmation: 'UPDATE' }),
  }),
};
