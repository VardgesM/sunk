import { request } from './client';
import type { Dashboard, DashboardDetail, DashboardInput, Widget, WidgetInput, WidgetLayout } from '../types/dashboards';
export const dashboardsApi = {
  async all(signal?: AbortSignal) {
    const rows: Dashboard[] = [];
    for (let offset = 0; ; offset += 500) {
      const batch = await request<Dashboard[]>(`/dashboards?limit=500&offset=${offset}`, { signal });
      rows.push(...batch); if (batch.length < 500) return rows;
    }
  },
  get: (id: number, signal?: AbortSignal) => request<DashboardDetail>(`/dashboards/${id}`, { signal }),
  create: (body: DashboardInput) => request<DashboardDetail>('/dashboards', { method: 'POST', body: JSON.stringify(body) }),
  edit: (id: number, body: Partial<DashboardInput>) => request<DashboardDetail>(`/dashboards/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  remove: (id: number) => request<void>(`/dashboards/${id}`, { method: 'DELETE' }),
  addWidget: (id: number, body: WidgetInput) => request<Widget>(`/dashboards/${id}/widgets`, { method: 'POST', body: JSON.stringify(body) }),
  editWidget: (id: number, body: WidgetInput) => request<Widget>(`/dashboard-widgets/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  removeWidget: (id: number) => request<void>(`/dashboard-widgets/${id}`, { method: 'DELETE' }),
  layout: (id: number, revision: number, layouts: (WidgetLayout & { widget_id: number })[]) => request<DashboardDetail>(`/dashboards/${id}/layout`, { method: 'PATCH', body: JSON.stringify({ revision, layouts }) }),
};
