import { useEffect, useState } from 'react';
import { Alert, Autocomplete, Box, Button, Stack, TextField, Typography, createFilterOptions } from '@mui/material';
import { tagsApi } from '../api/configuration';
import type { Tag } from '../types/configuration';
import TagHistory from '../components/TagHistory';

// Bound menu DOM size while retaining client-side search over the fetched metadata.
const filterTags = createFilterOptions<Tag>({ limit: 80, stringify: tag => `${tag.name} ${tag.key} ${tag.unit ?? ''}` });

export default function HistoryPage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [selected, setSelected] = useState<Tag | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, retry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    tagsApi.all(controller.signal).then(rows => { if (!controller.signal.aborted) { setTags(rows); setError(''); setLoading(false); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'Could not load Tags'); setLoading(false); } });
    return () => controller.abort();
  }, [revision]);
  return <Stack spacing={2} sx={{ minWidth: 0, overflowWrap: 'anywhere', '& .MuiAlert-message': { minWidth: 0, overflowWrap: 'anywhere' } }}>
    <Typography component="h1" variant="h4">History</Typography>
    <Typography color="text.secondary">Choose a Tag to inspect stored values. Current live values and historical records are separate.</Typography>
    {error && <Alert severity="error" action={<Button onClick={() => { setLoading(true); retry(value => value + 1); }} sx={{ minHeight: 44 }}>Retry</Button>}>{error}</Alert>}
    <Autocomplete fullWidth options={tags} value={selected} onChange={(_, tag) => setSelected(tag)} filterOptions={filterTags}
      loading={loading} getOptionKey={tag => tag.id} getOptionLabel={tag => tag.name} isOptionEqualToValue={(a, b) => a.id === b.id}
      noOptionsText={tags.length ? 'No matching Tags' : 'No Tags configured'}
      slotProps={{ popper: { sx: { maxWidth: 'calc(100vw - 32px)' } }, listbox: { sx: { '& .MuiAutocomplete-option': { minHeight: { xs: 44, sm: 44 }, whiteSpace: 'normal', overflowWrap: 'anywhere' } } } }}
      renderOption={(props, tag) => { const { key, ...rest } = props; return <Box component="li" key={key} {...rest}>
        <Box sx={{ minWidth: 0 }}><Typography fontWeight={600}>{tag.name}</Typography><Typography variant="caption" color="text.secondary">{tag.key}{tag.unit ? ` · ${tag.unit}` : ''}</Typography></Box>
      </Box>; }}
      renderInput={params => <TextField {...params} label="History Tag" helperText="Search by name, key or unit. Up to 80 matches are shown; type to narrow the list." />} />
    {loading && <Typography role="status">Loading Tags…</Typography>}
    {selected ? <>
      <Box><Typography component="h2" variant="h6">{selected.name}</Typography><Typography variant="body2" color="text.secondary">{selected.key}{selected.unit ? ` · Unit: ${selected.unit}` : ''}</Typography></Box>
      <TagHistory tagId={selected.id} showHeading={false} />
    </> : <Box sx={{ minHeight: { xs: 320, sm: 420 }, display: 'grid', placeItems: 'center', p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}>
      <Typography color="text.secondary">No Tag selected. Choose a Tag above to view its history.</Typography>
    </Box>}
  </Stack>;
}
