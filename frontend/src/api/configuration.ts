import { request } from './client';
import type { Connection, Device, Entity, Input, Location, Tag } from '../types/configuration';

export interface CrudApi<T extends Entity> {
  list: (query?: string, signal?: AbortSignal) => Promise<T[]>;
  all: (signal?: AbortSignal) => Promise<T[]>;
  get: (id: number) => Promise<T>;
  create: (value: Input<T>) => Promise<T>;
  update: (id: number, value: Partial<Input<T>>) => Promise<T>;
  remove: (id: number) => Promise<void>;
}

function crud<T extends Entity>(path: string): CrudApi<T> {
  return {
    list: (query = '', signal) => request<T[]>(`${path}?${query}`, { signal }),
    async all(signal) {
      const rows: T[] = [];
      for (let offset = 0; ; offset += 500) {
        const batch = await request<T[]>(`${path}?limit=500&offset=${offset}`, { signal });
        rows.push(...batch);
        if (batch.length < 500) return rows;
      }
    },
    get: (id) => request<T>(`${path}/${id}`),
    create: (value) => request<T>(path, { method: 'POST', body: JSON.stringify(value) }),
    update: (id, value) => request<T>(`${path}/${id}`, { method: 'PATCH', body: JSON.stringify(value) }),
    remove: (id) => request<void>(`${path}/${id}`, { method: 'DELETE' }),
  };
}

export const locationsApi = crud<Location>('/locations');
export const connectionsApi = crud<Connection>('/connections');
export const devicesApi = crud<Device>('/devices');
export const tagsApi = crud<Tag>('/tags');

export function editable<T extends Entity>(row: T): Input<T> {
  return Object.fromEntries(Object.entries(row).filter(([key]) =>
    !['id', 'created_at', 'updated_at', 'connection_protocol'].includes(key))) as Input<T>;
}
