import { Chip, type ChipProps } from '@mui/material';

const colors: Record<string, ChipProps['color']> = {
  GOOD: 'success', ONLINE: 'success', CONNECTED: 'success', SUCCESS: 'success', SUCCEEDED: 'success', Enabled: 'success',
  BAD: 'error', COMM_ERROR: 'error', OFFLINE: 'error', ERROR: 'error', FAILED: 'error',
  STALE: 'warning', DEGRADED: 'warning', EXPIRED: 'warning', DISCONNECTED: 'warning',
  PENDING: 'info', PENDING_EDGE: 'info', DELIVERED: 'info', QUEUED: 'info', EXECUTING: 'info', VERIFYING: 'info', CONNECTING: 'info',
};

export default function StatusBadge({ label, title }: { label: string; title?: string }) {
  return <Chip size="small" label={label} title={title} color={colors[label] ?? 'default'}
    sx={{ alignSelf: 'flex-start', maxWidth: '100%', height: 'auto', minHeight: 24,
      '& .MuiChip-label': { whiteSpace: 'normal', overflowWrap: 'anywhere', py: 0.25 } }} />;
}
