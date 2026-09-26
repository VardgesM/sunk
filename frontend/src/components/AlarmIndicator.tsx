import { useEffect, useState } from 'react';
import { Chip } from '@mui/material';
import { Link } from 'react-router-dom';
import { alarmsApi } from '../api/alarms';
import { useAlarmRefresh } from '../hooks/useAlarmRefresh';
export default function AlarmIndicator() {
  const revision = useAlarmRefresh();
  const [summary, setSummary] = useState<{active: number; critical: number} | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    void alarmsApi.summary().then(value => { if (active) { setSummary(value); setError(false); } }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [revision]);
  return <Chip component={Link} to="/alarms" clickable color={error ? 'warning' : summary?.critical ? 'error' : 'default'} label={error ? 'Alarms: unavailable' : summary ? `Alarms: ${summary.active}${summary.critical ? ` / ${summary.critical} CRITICAL` : ''}` : 'Alarms: loading'} />;
}
