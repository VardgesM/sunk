import { request } from './client';

export interface BackupManifest { format_version: number; created_at: string; application_version: string; migration_revision: string; deployment_mode: string; postgres_major: number }
export interface Backup { id: string; kind: 'backup' | 'upload'; created_at: string; size: number; status: string; manifest: BackupManifest | null; error: string | null }
export interface ConfigurationFile { format: 'modbus-monitor-config'; version: number; exported_at: string; application_version: string; data: Record<string, {id: string; values: Record<string, unknown>}[]> }
export interface ImportPreview { valid: boolean; counts: Record<string, number>; warnings: string[] }
const base = '/system';
export const backupsApi = {
  list: () => request<Backup[]>(`${base}/backups`),
  create: (passphrase: string) => request<Backup>(`${base}/backups`, { method: 'POST', body: JSON.stringify({passphrase}) }),
  remove: (id: string) => request<void>(`${base}/backups/${id}`, {method: 'DELETE'}),
  upload: (file: File) => request<Backup>(`${base}/backups/upload`, {method: 'POST', body: file, headers: {'Content-Type': 'application/octet-stream'}}),
  validate: (id: string, passphrase: string) => request<Backup>(`${base}/restores/${id}/validate`, {method: 'POST', body: JSON.stringify({passphrase})}),
  confirm: (id: string) => request<Backup>(`${base}/restores/${id}/confirm`, {method: 'POST', body: JSON.stringify({confirmation: 'RESTORE'})}),
  cancel: (id: string) => request<Backup>(`${base}/restores/${id}/cancel`, {method: 'POST'}),
  export: () => request<ConfigurationFile>(`${base}/configuration/export`, {method: 'POST'}),
  preview: (document: ConfigurationFile) => request<ImportPreview>(`${base}/configuration/preview`, {method: 'POST', body: JSON.stringify(document)}),
  import: (document: ConfigurationFile) => request<{imported: Record<string, number>}>(`${base}/configuration/import`, {method: 'POST', body: JSON.stringify({document, confirmation: 'IMPORT'})}),
};
