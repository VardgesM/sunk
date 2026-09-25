import { useState } from 'react';
import { Alert, MenuItem } from '@mui/material';
import { editable, locationsApi } from '../api/configuration';
import EntityEditor from '../components/EntityEditor';
import ManagementPage from '../components/ManagementPage';
import { NumberInput, SelectInput, TextInput } from '../components/ConfigurationFields';
import { useOptions } from '../hooks/useOptions';
import type { Location, LocationInput } from '../types/configuration';

function locationPath(row: Location, rows: Location[]): string {
  const names = [row.name];
  const seen = new Set([row.id]);
  let parent = rows.find((item) => item.id === row.parent_id);
  while (parent && !seen.has(parent.id)) {
    names.unshift(parent.name); seen.add(parent.id);
    const parentId = parent.parent_id;
    parent = rows.find((item) => item.id === parentId);
  }
  return names.join(' / ');
}

export default function LocationsPage() {
  const [revision, setRevision] = useState(0);
  const locations = useOptions(locationsApi, revision);
  return <ManagementPage title="Locations" api={locationsApi} onChanged={() => setRevision((value) => value + 1)}
    filters={locations.error && <Alert severity="error" sx={{ mb: 2 }}>Location parent options could not be loaded: {locations.error}</Alert>}
    columns={[
      { label: 'Location', render: (row) => locationPath(row, locations.rows) },
      { label: 'Sort order', render: (row) => row.sort_order },
      { label: 'Description', render: (row) => row.description || '—' },
    ]}
    editor={(row, save, cancel) => <EntityEditor<LocationInput>
      initial={row ? editable(row) : { name: '', parent_id: null, description: null, sort_order: 0 }} onSave={save} onCancel={cancel}>
      {(value, change) => <>
        {locations.error && <Alert severity="error">{locations.error}. Close and refresh to retry loading parents.</Alert>}
        <TextInput label="Name" value={value.name} onChange={(next) => change('name', next)} required />
        <SelectInput label="Parent location" value={value.parent_id ?? ''} onChange={(next) => change('parent_id', next ? Number(next) : null)} disabled={locations.loading || !!locations.error}>
          <MenuItem value="">None (root location)</MenuItem>
          {locations.rows.filter((item) => item.id !== row?.id).map((item) => <MenuItem key={item.id} value={item.id}>{locationPath(item, locations.rows)}</MenuItem>)}
        </SelectInput>
        <NumberInput label="Sort order" value={value.sort_order} onChange={(next) => change('sort_order', next ?? 0)} required />
        <TextInput label="Description" value={value.description} onChange={(next) => change('description', next || null)} multiline />
      </>}
    </EntityEditor>} />;
}
