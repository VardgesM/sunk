import { useEffect, useState } from 'react';
import { Alert, Paper, Stack, Typography } from '@mui/material';
import { getSystemInfo, type SystemInfo } from '../api/runtime';

export default function ApplicationInfo() {
  const [info, setInfo] = useState<SystemInfo>();
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    void getSystemInfo(controller.signal).then(data => {
      if (!controller.signal.aborted) setInfo(data);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(String(reason));
    });
    return () => controller.abort();
  }, []);

  return <Paper variant="outlined" sx={{ p: 2 }}>
    <Stack spacing={1} sx={{ overflowWrap: 'anywhere' }}>
      <Typography component="h2" variant="h6">Application information</Typography>
      {error ? <Alert severity="error">Unable to load application information: {error}</Alert>
        : !info ? <Typography role="status">Loading application information...</Typography>
        : <>
          <Typography>Application version: {info.application_version}</Typography>
          <Typography>Database revision: {info.database_revision ?? 'Not initialized'}</Typography>
          <Typography>Application mode: {info.application_mode}</Typography>
        </>}
    </Stack>
  </Paper>;
}
