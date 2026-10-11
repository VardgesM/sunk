import Can from '../auth/Can';
import { usePermission } from '../auth/context';
import { useEffect, useState, type ReactNode } from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Paper, Snackbar, Stack, Typography } from '@mui/material';
import ResponsiveDataView, { type Column } from './data/ResponsiveDataView';
import RowActions from './data/RowActions';
import { shellLayout } from '../layout/tokens';
import type { CrudApi } from '../api/configuration';
import type { Entity, Input } from '../types/configuration';

export default function ManagementPage<T extends Entity>({ title, api, columns, mobile, editor, query = '', filters, onChanged }: {
  title: string; api: CrudApi<T>; columns: Column<T>[]; query?: string; filters?: ReactNode;
  mobile: (row: T, actions: ReactNode) => ReactNode;
  editor: (row: T | null, save: (value: Input<T>) => Promise<void>, cancel: () => void) => ReactNode;
  onChanged?: () => void;
}) {
  const [rows, setRows] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [offset, setOffset] = useState(0);
  const [edit, setEdit] = useState<T | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<T>();
  const [deleteError, setDeleteError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const canConfigure = usePermission('configure');
  const pageSize = 50;
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true); setError('');
      try { setRows(await api.list(`${query}&limit=${pageSize}&offset=${offset}`, controller.signal)); }
      catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not load records'); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [api, query, offset, revision]);
  function changed(message: string) {
    setRevision((value) => value + 1); setNotice(message); onChanged?.();
  }
  return (
    <Box sx={{ minWidth: 0, overflowWrap: 'anywhere', '& .MuiAlert-message': { minWidth: 0 } }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} spacing={2} sx={{ mb: 3 }}>
        <Typography component="h1" variant="h4">{title}</Typography>
        <Can permission="configure"><Button variant="contained" sx={{ minHeight: shellLayout.touchTarget }} onClick={() => setEdit(null)}>Create</Button></Can>
      </Stack>
      {filters}
      {error && <Alert severity="error" action={<Button color="inherit" onClick={() => setRevision((value) => value + 1)}>Retry</Button>}>{error}</Alert>}
      {loading ? <Box role="status" sx={{ p: 3 }}><CircularProgress size={24} aria-label={`Loading ${title}`} /></Box> : !error && (
        rows.length === 0 ? <Paper variant="outlined" sx={{ p: 3 }}><Typography>{query ? 'No results match these filters.' : `No ${title.toLowerCase()} configured.`}</Typography></Paper> :
          <ResponsiveDataView label={title} rows={rows} columns={[...columns, ...(canConfigure ? [{ label: 'Actions', render: (row: T) => <Stack direction="row" useFlexGap flexWrap="wrap">
            <Button sx={{ minHeight: shellLayout.touchTarget }} aria-label={`Edit ${row.name}`} onClick={() => setEdit(row)}>Edit</Button>
            <Button sx={{ minHeight: shellLayout.touchTarget }} color="error" aria-label={`Delete ${row.name}`} onClick={() => { setDeleting(row); setDeleteError(''); }}>Delete</Button>
          </Stack> }] : [])]}
            card={row => mobile(row, canConfigure ? <RowActions name={row.name} actions={[
              { label: 'Edit', run: () => setEdit(row) },
              { label: 'Delete', destructive: true, run: () => { setDeleting(row); setDeleteError(''); } },
            ]} /> : null)} />
      )}
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mt: 2, '& .MuiButton-root': { minHeight: shellLayout.touchTarget } }}>
        <Button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</Button>
        <Typography variant="body2">Page {offset / pageSize + 1}</Typography>
        <Button disabled={loading || !!error || rows.length < pageSize} onClick={() => setOffset(offset + pageSize)}>Next</Button>
      </Stack>
      <Dialog open={edit !== undefined} fullWidth maxWidth="sm" disableEscapeKeyDown>
        <DialogTitle sx={{ overflowWrap: 'anywhere' }}>{edit ? `Edit ${edit.name}` : `Create ${title.toLowerCase().replace(/s$/, '')}`}</DialogTitle>
        {edit !== undefined && editor(edit, async (value) => {
          if (edit) await api.update(edit.id, value); else await api.create(value);
          setEdit(undefined); changed('Configuration saved');
        }, () => setEdit(undefined))}
      </Dialog>
      <Dialog open={!!deleting} onClose={() => { if (!busy) setDeleting(undefined); }} fullWidth maxWidth="xs">
        <DialogTitle sx={{ overflowWrap: 'anywhere' }}>Delete {deleting?.name}?</DialogTitle>
        <DialogContent><DialogContentText>This cannot be undone. Referenced configuration cannot be deleted.</DialogContentText>{deleteError && <Alert severity="error" sx={{ mt: 2 }}>{deleteError}</Alert>}</DialogContent>
        <DialogActions><Can permission="configure"><Button disabled={busy} onClick={() => setDeleting(undefined)}>Cancel</Button></Can><Can permission="configure"><Button color="error" disabled={busy} onClick={() => {
          if (!deleting) return;
          setBusy(true);
          void api.remove(deleting.id).then(() => { setDeleting(undefined); if (rows.length === 1 && offset > 0) setOffset(offset - pageSize); changed('Configuration deleted'); })
            .catch((reason: unknown) => setDeleteError(reason instanceof Error ? reason.message : 'Delete failed')).finally(() => setBusy(false));
        }}>{busy ? 'Deleting…' : 'Delete'}</Button></Can></DialogActions>
      </Dialog>
      <Snackbar open={!!notice} autoHideDuration={4000} onClose={() => setNotice('')}><Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert></Snackbar>
    </Box>
  );
}
