import { Chip, Tooltip } from '@mui/material';
import { useHealth } from '../hooks/useHealth';

export default function HealthStatus() {
  const { status, message } = useHealth();
  return (
    <Tooltip title={`${message}. Reports API availability only.`}>
      <Chip role="status" aria-live="polite" size="small"
        color={status === 'ok' ? 'success' : status === 'error' ? 'error' : 'default'}
        label={status === 'error' ? 'API unavailable' : message} />
    </Tooltip>
  );
}
