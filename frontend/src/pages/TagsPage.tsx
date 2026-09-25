import { useState } from 'react';
import { Alert, Button, MenuItem, Stack, TextField } from '@mui/material';
import { editable, devicesApi, tagsApi } from '../api/configuration';
import EntityEditor from '../components/EntityEditor';
import HistorySettings from '../components/HistorySettings';
import ManagementPage from '../components/ManagementPage';
import { NumberInput, SelectInput, TextInput, Toggle } from '../components/ConfigurationFields';
import { choices } from '../components/choices';
import { LiveConnectionStatus, LiveValue } from '../components/LiveValues';
import { useOptions } from '../hooks/useOptions';
import type { DataType, Order, RegisterType, TagInput } from '../types/configuration';

const registerTypes: RegisterType[] = ['coil', 'discrete_input', 'input_register', 'holding_register'];
const numericTypes: DataType[] = ['uint16', 'int16', 'uint32', 'int32', 'float32', 'uint64', 'int64', 'float64'];
const initial: TagInput = {
  name: '', key: '', device_id: 0, register_type: 'holding_register', address: 0,
  data_type: 'uint16', byte_order: 'big', word_order: 'big', scale: 1, offset: 0,
  unit: null, poll_interval_ms: 1000, writable: false, history_enabled: false,
  history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null,
  enabled: true, min_value: null, max_value: null, description: null,
};

export default function TagsPage() {
  const devices = useOptions(devicesApi);
  const [search, setSearch] = useState('');
  const [device, setDevice] = useState('');
  const [register, setRegister] = useState('');
  const [enabled, setEnabled] = useState('');
  const [query, setQuery] = useState('');
  return <ManagementPage key={query} title="Tags" api={tagsApi} query={query}
    filters={<>
      <LiveConnectionStatus />
      {devices.error && <Alert severity="error" sx={{ mb: 2 }}>Device options could not be loaded: {devices.error}</Alert>}
      <Stack component="form" direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 2 }} onSubmit={(event) => {
      event.preventDefault();
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (device) params.set('device_id', device);
      if (register) params.set('register_type', register);
      if (enabled) params.set('enabled', enabled);
      setQuery(params.toString());
    }}>
      <TextField fullWidth label="Search name or key" value={search} onChange={(event) => setSearch(event.target.value)} />
      <SelectInput label="Device filter" value={device} onChange={setDevice}><MenuItem value="">All devices</MenuItem>{devices.rows.map((item) => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</SelectInput>
      <SelectInput label="Register filter" value={register} onChange={setRegister}><MenuItem value="">All registers</MenuItem>{choices(registerTypes)}</SelectInput>
      <SelectInput label="Enabled filter" value={enabled} onChange={setEnabled}><MenuItem value="">All states</MenuItem><MenuItem value="true">Enabled</MenuItem><MenuItem value="false">Disabled</MenuItem></SelectInput>
      <Button type="submit">Apply</Button><Button onClick={() => { setSearch(''); setDevice(''); setRegister(''); setEnabled(''); setQuery(''); }}>Reset</Button>
    </Stack></>}
    columns={[
      { label: 'Name / Key', render: (row) => <><a href={`/tags/${row.id}`}>{row.name}</a><br /><small>{row.key}</small></> },
      { label: 'Device', render: (row) => devices.rows.find((item) => item.id === row.device_id)?.name ?? `#${row.device_id}` },
      { label: 'Register type', render: (row) => row.register_type },
      { label: 'Address (zero-based)', render: (row) => row.address },
      { label: 'Data type', render: (row) => row.data_type },
      { label: 'Current value', render: (row) => <LiveValue tagId={row.id} field="value" /> },
      { label: 'Unit', render: (row) => row.unit ?? '—' },
      { label: 'Quality', render: (row) => <LiveValue tagId={row.id} field="quality" /> },
      { label: 'Last successful update', render: (row) => <LiveValue tagId={row.id} field="time" /> },
      { label: 'Enabled', render: (row) => row.enabled ? 'Yes' : 'No' },
      { label: 'Value source', render: (row) => <LiveValue tagId={row.id} field="source" /> },
    ]}
    editor={(row, save, cancel) => <EntityEditor<TagInput> initial={row ? editable(row) : initial} onSave={save} onCancel={cancel}>
      {(value, change) => {
        const bit = value.register_type === 'coil' || value.register_type === 'discrete_input';
        const canWrite = value.register_type === 'coil' || value.register_type === 'holding_register';
        return <>
          {devices.error && <Alert severity="error">{devices.error}. Close and refresh to retry loading devices.</Alert>}
          {!devices.loading && !devices.error && devices.rows.length === 0 && <Alert severity="info">Create a device before adding a tag.</Alert>}
          <TextInput label="Name" value={value.name} onChange={(next) => change('name', next)} required />
          <TextInput label="Key" value={value.key} onChange={(next) => change('key', next)} required helperText="Unique; lowercase letter first, then lowercase letters, digits or underscores. Maximum 64 characters." />
          <SelectInput label="Device" value={value.device_id || ''} onChange={(next) => change('device_id', Number(next))} required disabled={devices.loading || !!devices.error}>{devices.rows.map((item) => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</SelectInput>
          <SelectInput label="Register type" value={value.register_type} onChange={(next) => {
            const type = next as RegisterType;
            change('register_type', type);
            const isBit = type === 'coil' || type === 'discrete_input';
            change('data_type', isBit ? 'bool' : value.data_type === 'bool' ? 'uint16' : value.data_type);
            if (type === 'discrete_input' || type === 'input_register') change('writable', false);
          }}>{choices(registerTypes)}</SelectInput>
          <NumberInput label="Address (zero-based)" value={value.address} onChange={(next) => change('address', next ?? 0)} min={0} max={65535} required helperText="Protocol offset 0–65535. Vendor notation such as 40001 is NOT converted automatically." />
          <SelectInput label="Data type" value={value.data_type} onChange={(next) => change('data_type', next as DataType)}>{choices(bit ? ['bool'] : numericTypes)}</SelectInput>
          {!bit && <>
            <SelectInput label="Byte order" value={value.byte_order} onChange={(next) => change('byte_order', next as Order)}>{choices(['big', 'little'])}</SelectInput>
            {!['uint16', 'int16'].includes(value.data_type) && <SelectInput label="Word order" value={value.word_order} onChange={(next) => change('word_order', next as Order)}>{choices(['big', 'little'])}</SelectInput>}
          </>}
          <TextInput label="Unit" value={value.unit} onChange={(next) => change('unit', next || null)} />
          <NumberInput label="Scale" value={value.scale} onChange={(next) => change('scale', next ?? 0)} step="any" required />
          <NumberInput label="Offset" value={value.offset} onChange={(next) => change('offset', next ?? 0)} step="any" required />
          <NumberInput label="Minimum value" value={value.min_value} onChange={(next) => change('min_value', next)} step="any" />
          <NumberInput label="Maximum value" value={value.max_value} onChange={(next) => change('max_value', next)} step="any" />
          <NumberInput label="Poll interval (ms)" value={value.poll_interval_ms} onChange={(next) => change('poll_interval_ms', next ?? 0)} min={1} required helperText="Worker collection interval. Simulation requires development opt-in; real Modbus is not implemented." />
          <Toggle label="Writable" value={value.writable} onChange={(next) => change('writable', next)} disabled={!canWrite} />
          <HistorySettings value={value} change={change} />
          <Toggle label="Enabled" value={value.enabled} onChange={(next) => change('enabled', next)} />
          <TextInput label="Description" value={value.description} onChange={(next) => change('description', next || null)} multiline />
        </>;
      }}
    </EntityEditor>} />;
}
