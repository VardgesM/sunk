export type WidgetType = 'value' | 'gauge' | 'chart' | 'boolean' | 'switch' | 'setpoint' | 'alarms' | 'text';
export type Breakpoint = 'lg' | 'md' | 'sm';
export interface WidgetLayout { breakpoint: Breakpoint; x: number; y: number; w: number; h: number }
export interface WidgetConfig {
  decimals?: number; show_unit?: boolean; show_quality?: boolean; show_last_update?: boolean;
  min?: number; max?: number; unit?: string | null; warning_threshold?: number | null; critical_threshold?: number | null;
  range_hours?: number; legend?: boolean; refresh_seconds?: number; on_label?: string; off_label?: string;
  confirmation_required?: boolean; severities?: ('INFO' | 'WARNING' | 'CRITICAL')[]; active_only?: boolean; maximum_rows?: number; text?: string;
}
export interface WidgetInput { type: WidgetType; title: string; configuration: WidgetConfig; tag_ids: number[]; layouts: WidgetLayout[] }
export interface Widget extends WidgetInput { id: number; dashboard_id: number; created_at: string; updated_at: string }
export interface DashboardInput { name: string; slug: string; description: string | null; is_default: boolean }
export interface Dashboard extends DashboardInput { id: number; revision: number; created_at: string; updated_at: string }
export interface DashboardDetail extends Dashboard { widgets: Widget[] }
