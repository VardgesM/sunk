import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Alert, Box, Button, Divider, Stack, Typography } from '@mui/material';
import { devicesApi, tagsApi } from '../api/configuration';
import type { Tag } from '../types/configuration';
import { LiveConnectionStatus, LiveValue } from '../components/LiveValues';
import ManualControl from '../components/ManualControl';
import TagHistory from '../components/TagHistory';

export default function TagDetailsPage() {
  const { id } = useParams();
  const [state, setState] = useState<{ tag?: Tag; device?: string; error?: string }>({});
  useEffect(() => {
    let active = true;
    tagsApi.get(Number(id)).then(async (tag) => {
      const device = await devicesApi.get(tag.device_id);
      if (active) setState({ tag, device: device.name });
    }).catch((error: unknown) => { if (active) setState({ error: error instanceof Error ? error.message : 'Could not load tag' }); });
    return () => { active = false; };
  }, [id]);
  const tag = state.tag;
  return <Stack spacing={2}>
    <Button component={Link} to="/tags" sx={{ alignSelf: 'flex-start' }}>Back to Tags</Button>
    {state.error && <Alert severity="error">{state.error}</Alert>}
    {!tag && !state.error && <Typography role="status">Loading tag…</Typography>}
    {tag && <>
      <Typography component="h1" variant="h4">{tag.name}</Typography>
      <LiveConnectionStatus />
      <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '180px 1fr' }, gap: 1, '& dt': { fontWeight: 600 }, '& dd': { m: 0, overflowWrap: 'anywhere' } }}>
        <dt>Key</dt><dd>{tag.key}</dd><dt>Device</dt><dd>{state.device}</dd>
        <dt>Register</dt><dd>{tag.register_type}, address {tag.address} (zero-based)</dd>
        <dt>Data type / unit</dt><dd>{tag.data_type} / {tag.unit ?? '—'}</dd>
        <dt>Enabled</dt><dd>{tag.enabled ? 'Yes' : 'No'}</dd>
        <dt>Current value</dt><dd><LiveValue tagId={tag.id} field="value" /> {tag.unit}</dd>
        <dt>Quality</dt><dd><LiveValue tagId={tag.id} field="quality" /></dd>
        <dt>Value source</dt><dd><LiveValue tagId={tag.id} field="source" /></dd>
        <dt>Communication error</dt><dd><LiveValue tagId={tag.id} field="error" /></dd>
        <dt>State updated</dt><dd><LiveValue tagId={tag.id} field="updated" /></dd>
        <dt>Last successful update</dt><dd><LiveValue tagId={tag.id} field="time" /></dd>
        <dt>Poll interval</dt><dd>{tag.poll_interval_ms} ms</dd>
        <dt>History policy</dt><dd>{tag.history_enabled ? 'Enabled' : 'Disabled'} / {tag.history_mode}; interval {tag.history_interval_ms ?? '—'} ms; threshold {tag.history_change_threshold ?? '—'}; retention {tag.history_retention_days ? `${tag.history_retention_days} days` : 'indefinite'}</dd>
      </Box>
      {tag.writable && <ManualControl key={tag.id} tag={tag} />}
      <Divider /><TagHistory key={tag.id} tagId={tag.id} />
    </>}
  </Stack>;
}
