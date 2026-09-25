import { Alert, Chip, Stack, Tooltip } from '@mui/material';
import { useLiveStatus, useTagValue } from '../hooks/useLiveValues';

export function LiveConnectionStatus() {
  const status = useLiveStatus();
  return <Stack spacing={1} sx={{ mb: 2 }}>
    <Chip role="status" label={status.state} color={status.state === 'Live' ? 'success' : 'default'} sx={{ alignSelf: 'flex-start' }} />
    {status.error && <Alert severity="warning">{status.error}</Alert>}
  </Stack>;
}

export function LiveValue({ tagId, field, control = false }: { tagId: number; field: 'value' | 'quality' | 'time' | 'source' | 'error' | 'updated'; control?: boolean }) {
  const current = useTagValue(tagId);
  if (field === 'quality') return <Tooltip title={current?.error ?? ''}><Chip size="small"
    label={current?.quality ?? 'Awaiting value'}
    color={current?.quality === 'GOOD' ? 'success' : current?.quality === 'COMM_ERROR' || current?.quality === 'BAD' ? 'error' : 'default'} /></Tooltip>;
  if (!current) return <>—</>;
  if (field === 'source') return <>{current.source ?? 'Unknown / no sample'}</>;
  if (field === 'error') return <>{current.error ?? 'None'}</>;
  if (field === 'updated') return <>{current.updated_at ? new Date(current.updated_at).toLocaleString() : '—'}</>;
  if (field === 'time') return <Tooltip title={`State updated: ${current.updated_at ?? 'never'}`}>
    <span>{current.source_timestamp ? new Date(current.source_timestamp).toLocaleString() : '—'}</span>
  </Tooltip>;
  if (current.value_boolean !== null) return <>{control ? current.value_boolean ? 'ON' : 'OFF' : current.value_boolean ? 'True' : 'False'}</>;
  if (current.value_text !== null) return <>{current.value_text}</>;
  if (current.value_numeric !== null) return <Tooltip title={current.value_numeric_exact ?? ''}><span>
    {Number.isInteger(current.value_numeric) && !Number.isSafeInteger(current.value_numeric)
      ? current.value_numeric_exact : current.value_numeric.toLocaleString(undefined, { maximumSignificantDigits: 12 })}
  </span></Tooltip>;
  return <>—</>;
}
