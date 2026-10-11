import type { Widget } from '../types/dashboards';

// These are the existing builder breakpoints, measured inside the page container.
export const dashboardBreakpoints = { lg: 1000, md: 600, sm: 0 };

export function mobileWidgetOrder(widgets: Widget[]): Widget[] {
  return [...widgets].sort((a, b) => {
    // View-only priority; never write the derived ordering back to the builder.
    const priority = Number(b.type === 'alarms') - Number(a.type === 'alarms');
    const left = a.layouts.find(layout => layout.breakpoint === 'sm');
    const right = b.layouts.find(layout => layout.breakpoint === 'sm');
    return priority || (left?.y ?? 0) - (right?.y ?? 0) || (left?.x ?? 0) - (right?.x ?? 0) || a.id - b.id;
  });
}
