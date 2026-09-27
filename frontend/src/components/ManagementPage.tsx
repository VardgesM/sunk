import Can from '../auth/Can';
import { useEffect, useState, type ReactNode } from 'react';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Paper, Snackbar, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import type { CrudApi } from '../api/configuration';
import type { Entity, Input } from '../types/configuration';

export interface Column<T> { label: string; render: (row: T) => ReactNode }

export default function ManagementPage<T extends Entity>({ title, api, columns, editor, query = '', filters, onChanged }: {
  title: string; api: CrudApi<T>; columns: Column<T>[]; query?: string; filters?: ReactNode;
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
    <Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} spacing={2} sx={{ mb: 3 }}>
        <Typography component="h1" variant="h4">{title}</Typography>
        <Can permission="configure"><Button variant="contained" onClick={() => setEdit(null)}>Create</Button></Can>
      </Stack>
      {filters}
      {error && <Alert severity="error" action={<Button color="inherit" onClick={() => setRevision((value) => value + 1)}>Retry</Button>}>{error}</Alert>}
      {loading ? <Box role="status" sx={{ p: 3 }}><CircularProgress size={24} aria-label={`Loading ${title}`} /></Box> : !error && (
        rows.length === 0 ? <Paper variant="outlined" sx={{ p: 3 }}><Typography>No matching {title.toLowerCase()}.</Typography></Paper> :
          <TableContainer component={Paper} variant="outlined">
            <Table size="small" aria-label={title}>
              <TableHead><TableRow>{columns.map((column) => <TableCell key={column.label}>{column.label}</TableCell>)}<TableCell>Actions</TableCell></TableRow></TableHead>
              <TableBody>{rows.map((row) => <TableRow key={row.id}>
                {columns.map((column) => <TableCell key={column.label} sx={{ overflowWrap: 'anywhere' }}>{column.render(row)}</TableCell>)}
                <TableCell><Stack direction="row"><Can permission="configure"><Button aria-label={`Edit ${row.name}`} onClick={() => setEdit(row)}>Edit</Button></Can><Can permission="configure"><Button color="error" aria-label={`Delete ${row.name}`} onClick={() => { setDeleting(row); setDeleteError(''); }}>Delete</Button></Can></Stack></TableCell>
              </TableRow>)}</TableBody>
            </Table>
          </TableContainer>
      )}
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mt: 2 }}>
        <Button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</Button>
        <Typography variant="body2">Page {offset / pageSize + 1}</Typography>
        <Button disabled={loading || !!error || rows.length < pageSize} onClick={() => setOffset(offset + pageSize)}>Next</Button>
      </Stack>
      <Dialog open={edit !== undefined} fullWidth maxWidth="sm" disableEscapeKeyDown>
        <DialogTitle>{edit ? `Edit ${edit.name}` : `Create ${title.toLowerCase().replace(/s$/, '')}`}</DialogTitle>
        {edit !== undefined && editor(edit, async (value) => {
          if (edit) await api.update(edit.id, value); else await api.create(value);
          setEdit(undefined); changed('Configuration saved');
        }, () => setEdit(undefined))}
      </Dialog>
      <Dialog open={!!deleting} onClose={() => { if (!busy) setDeleting(undefined); }} fullWidth maxWidth="xs">
        <DialogTitle>Delete {deleting?.name}?</DialogTitle>
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
