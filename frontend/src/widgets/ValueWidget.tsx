import { Alert, Chip, LinearProgress, Stack, Typography } from '@mui/material';
import { useTagValue } from '../hooks/useLiveValues';
import type { Tag } from '../types/configuration';
import type { Widget } from '../types/dashboards';

export default function ValueWidget({ widget, tag }: { widget: Widget; tag: Tag }) {
  const value = useTagValue(tag.id);
  const config = widget.configuration;
  if (!value) return <Alert severity="info">No current value. Tag may be unavailable.</Alert>;
  const unit = widget.type === 'gauge' ? config.unit ?? tag.unit : config.show_unit === false ? '' : tag.unit;
  let display = value.value_numeric_exact && Math.abs(Number(value.value_numeric_exact)) > Number.MAX_SAFE_INTEGER
    ? value.value_numeric_exact : value.value_numeric !== null ? value.value_numeric.toFixed(config.decimals ?? 2) : value.value_text ?? 'No value';
  if (tag.data_type === 'bool') display = value.value_boolean === null ? 'No value' : value.value_boolean ? config.on_label ?? 'ON' : config.off_label ?? 'OFF';
  const good = value.quality === 'GOOD';
  const min = config.min ?? 0, max = config.max ?? 100;
  const numeric = value.value_numeric;
  const level = numeric !== null && config.critical_threshold != null && numeric >= config.critical_threshold ? 'Critical range'
    : numeric !== null && config.warning_threshold != null && numeric >= config.warning_threshold ? 'Warning range' : 'Normal range';
  return <Stack spacing={1}>
    <Typography variant="h4" sx={{ overflowWrap: 'anywhere' }}>{display} {unit}</Typography>
    {!good && <Typography>Last known value - {value.quality ?? 'no quality'}</Typography>}
    {(config.show_quality !== false || !good) && <Chip label={value.quality ?? 'No quality'} color={good ? 'success' : 'warning'} size="small" />}
    {value.error && <Alert severity="warning">{value.error}</Alert>}
    {config.show_last_update !== false && <Typography variant="caption">Last update: {value.updated_at ? new Date(value.updated_at).toLocaleString() : 'Never'}</Typography>}
    {widget.type === 'gauge' && <>
      <LinearProgress aria-label={`${widget.title} gauge`} variant="determinate" value={good && numeric !== null ? Math.max(0, Math.min(100, (numeric - min) / (max - min) * 100)) : 0} color={level === 'Critical range' ? 'error' : level === 'Warning range' ? 'warning' : 'primary'} sx={{ height: 18, borderRadius: 2 }} />
      <Typography>{min} - {max} {unit}</Typography><Typography>{good ? level : 'Gauge unavailable until a GOOD sample'}</Typography>
      <Typography variant="caption">Visual thresholds only; no alarm rule is created.</Typography>
    </>}
  </Stack>;
}
