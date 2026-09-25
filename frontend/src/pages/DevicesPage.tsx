import { Alert, MenuItem } from '@mui/material';
import { editable, connectionsApi, devicesApi, locationsApi } from '../api/configuration';
import EntityEditor from '../components/EntityEditor';
import { DeviceState } from '../components/RuntimeStatus';
import ManagementPage from '../components/ManagementPage';
import { NumberInput, SelectInput, TextInput, Toggle } from '../components/ConfigurationFields';
import { useOptions } from '../hooks/useOptions';
import type { DeviceInput } from '../types/configuration';

export default function DevicesPage() {
  const connections = useOptions(connectionsApi);
  const locations = useOptions(locationsApi);
  return <ManagementPage title="Devices" api={devicesApi}
    filters={(connections.error || locations.error) && <Alert severity="error" sx={{ mb: 2 }}>Configuration options could not be loaded: {connections.error || locations.error}</Alert>}
    columns={[
      { label: 'Name', render: (row) => row.name },
      { label: 'Connection', render: (row) => connections.rows.find((item) => item.id === row.connection_id)?.name ?? `#${row.connection_id}` },
      { label: 'Protocol', render: (row) => row.connection_protocol === 'modbus_tcp' ? 'Modbus TCP' : 'Modbus RTU' },
      { label: 'Location', render: (row) => locations.rows.find((item) => item.id === row.location_id)?.name ?? '—' },
      { label: 'Slave ID', render: (row) => row.slave_id },
      { label: 'Enabled', render: (row) => row.enabled ? 'Yes' : 'No' },
      { label: 'Runtime', render: (row) => <DeviceState id={row.id} /> },
    ]}
    editor={(row, save, cancel) => <EntityEditor<DeviceInput>
      initial={row ? editable(row) : { name: '', connection_id: 0, location_id: null, slave_id: 1, enabled: true, description: null }} onSave={save} onCancel={cancel}>
      {(value, change) => <>
        {(connections.error || locations.error) && <Alert severity="error">{connections.error || locations.error}. Close and refresh to retry loading options.</Alert>}
        {!connections.loading && !connections.error && connections.rows.length === 0 && <Alert severity="info">Create a connection before adding a device.</Alert>}
        <TextInput label="Name" value={value.name} onChange={(next) => change('name', next)} required />
        <SelectInput label="Connection" value={value.connection_id || ''} onChange={(next) => change('connection_id', Number(next))} required disabled={connections.loading || !!connections.error}>
          {connections.rows.map((item) => <MenuItem key={item.id} value={item.id}>{item.name} ({item.protocol})</MenuItem>)}
        </SelectInput>
        <SelectInput label="Location" value={value.location_id ?? ''} onChange={(next) => change('location_id', next ? Number(next) : null)} disabled={locations.loading || !!locations.error}>
          <MenuItem value="">None</MenuItem>{locations.rows.map((item) => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
        </SelectInput>
        <NumberInput label="Slave ID" value={value.slave_id} onChange={(next) => change('slave_id', next ?? 0)} min={1} max={247} required helperText="Phase 2 supports unicast IDs 1–247 on both transports." />
        <Toggle label="Enabled" value={value.enabled} onChange={(next) => change('enabled', next)} />
        <TextInput label="Description" value={value.description} onChange={(next) => change('description', next || null)} multiline />
      </>}
    </EntityEditor>} />;
}
