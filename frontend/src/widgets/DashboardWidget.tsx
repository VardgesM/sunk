import { Component, lazy, Suspense, type ReactNode } from 'react';
import { Alert, Typography } from '@mui/material';
import type { Tag } from '../types/configuration';
import type { Widget } from '../types/dashboards';
import ValueWidget from './ValueWidget';
import AlarmWidget from './AlarmWidget';
import ManualControl from '../components/ManualControl';
const ChartWidget = lazy(() => import('./ChartWidget'));

class WidgetBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.error('Dashboard widget rendering failed', error); }
  render() { return this.state.failed ? <Alert severity="error">Widget could not render. Edit its configuration or reload.</Alert> : this.props.children; }
}
function Content({ widget, tags, editing }: { widget: Widget; tags: Map<number, Tag>; editing: boolean }) {
  const selected = widget.tag_ids.map(id => tags.get(id));
  if (selected.some(t => !t)) return <Alert severity="error">Configuration error: a referenced Tag is missing or unavailable.</Alert>;
  if (widget.type === 'text') return <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{widget.configuration.text}</Typography>;
  if (widget.type === 'alarms') return <AlarmWidget config={widget.configuration} />;
  const tag = selected[0];
  if (!tag) return <Alert severity="error">Configuration error: select a Tag.</Alert>;
  if (widget.type === 'chart') {
    if (selected.some(t => t?.data_type === 'bool') || new Set(selected.map(t => t?.unit ?? '')).size > 1) return <Alert severity="error">Chart requires compatible numeric Tags with the same unit.</Alert>;
    return <Suspense fallback={<Typography>Loading chart...</Typography>}><ChartWidget widget={widget} /></Suspense>;
  }
  if (['switch', 'setpoint'].includes(widget.type)) {
    const valid = tag.enabled && tag.writable && (widget.type === 'switch' ? tag.data_type === 'bool' && tag.register_type === 'coil' : tag.data_type !== 'bool' && tag.register_type === 'holding_register');
    if (!valid) return <Alert severity="warning">Control unavailable: Tag configuration is no longer writable or compatible.</Alert>;
    if (editing) return <Alert severity="info">Controls are unavailable while editing the dashboard.</Alert>;
    return <ManualControl tag={tag} confirmationRequired={widget.configuration.confirmation_required !== false} />;
  }
  if (widget.type === 'gauge' && tag.data_type === 'bool' || widget.type === 'boolean' && tag.data_type !== 'bool') return <Alert severity="error">Tag type no longer matches this widget.</Alert>;
  return <ValueWidget widget={widget} tag={tag} />;
}
export default function DashboardWidget(props: { widget: Widget; tags: Map<number, Tag>; editing: boolean }) {
  return <WidgetBoundary key={props.widget.updated_at}><Content {...props} /></WidgetBoundary>;
}
