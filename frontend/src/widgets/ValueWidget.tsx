import { Alert, Box, LinearProgress, Stack, Typography } from '@mui/material';
import StatusBadge from '../components/data/StatusBadge';
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
  return <Stack spacing={1.25} sx={{ minWidth: 0 }}>
    {!good && <Typography variant="body2" color="warning.dark" fontWeight={600}>Last known value · not a current GOOD reading</Typography>}
    <Typography component="p" aria-label={`${display}${unit ? ` ${unit}` : ''}`} sx={{ fontSize: '2.5rem', lineHeight: 1.15, fontWeight: 600, fontVariantNumeric: 'tabular-nums', overflowWrap: 'anywhere', color: good ? 'text.primary' : 'text.secondary' }}>
      {display}{unit && <> <Box component="span" sx={{ fontSize: '1.125rem', fontWeight: 400, color: 'text.secondary' }}>{unit}</Box></>}
    </Typography>
    {(config.show_quality !== false || !good) && <StatusBadge label={value.quality ?? 'No quality'} />}
    {value.error && <Alert severity="warning">{value.error}</Alert>}
    {config.show_last_update !== false && <Typography variant="caption" color="text.secondary">Last update: {value.updated_at ? <time dateTime={value.updated_at}>{new Date(value.updated_at).toLocaleString()}</time> : 'Never'}</Typography>}
    {widget.type === 'gauge' && <>
      {good && numeric !== null ? <LinearProgress aria-label={`${widget.title} gauge`} aria-valuetext={`${display} ${unit ?? ''}, ${level}`} variant="determinate" value={Math.max(0, Math.min(100, (numeric - min) / (max - min) * 100))} color={level === 'Critical range' ? 'error' : level === 'Warning range' ? 'warning' : 'primary'} sx={{ height: 12, borderRadius: 2 }} /> : <Box sx={{ height: 12, borderRadius: 2, bgcolor: 'action.disabledBackground' }} />}
      <Stack direction="row" justifyContent="space-between" gap={1}><Typography variant="caption">{min} {unit}</Typography><Typography variant="caption">{max} {unit}</Typography></Stack>
      <Typography variant="body2" fontWeight={600}>{good && numeric !== null ? level : 'Gauge unavailable until a GOOD sample'}</Typography>
      <Typography variant="caption" color="text.secondary">Visual thresholds only; no alarm rule is created.</Typography>
    </>}
  </Stack>;
}
