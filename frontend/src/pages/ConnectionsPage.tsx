import { editable, connectionsApi } from '../api/configuration';
import EntityEditor from '../components/EntityEditor';
import { ConnectionState, TestConnection } from '../components/RuntimeStatus';
import AutoAdapter from '../components/AutoAdapter';
import { MenuItem, Typography } from '@mui/material';
import SerialDiscovery from '../components/SerialDiscovery';
import ManagementPage from '../components/ManagementPage';
import { NumberInput, SelectInput, TextInput, Toggle } from '../components/ConfigurationFields';
import { choices } from '../components/choices';
import type { ConnectionInput, Protocol } from '../types/configuration';

const initial: ConnectionInput = {
  name: '', protocol: 'modbus_tcp', enabled: true, host: '', port: 502, timeout_ms: 1000,
  serial_port_mode: 'manual', usb_vid: null, usb_pid: null, usb_serial_number: null, usb_hardware_id: null, usb_manufacturer: null, usb_product: null, serial_probe_enabled: false,
  serial_port: null, baud_rate: null, parity: null, stop_bits: null, data_bits: null,
};

export default function ConnectionsPage() {
  return <ManagementPage title="Connections" api={connectionsApi}
    columns={[
      { label: 'Name', render: (row) => row.name },
      { label: 'Protocol', render: (row) => row.protocol === 'modbus_tcp' ? 'Modbus TCP' : 'Modbus RTU' },
      { label: 'Endpoint', render: (row) => row.protocol === 'modbus_tcp' ? `${row.host}:${row.port}` : row.serial_port_mode === 'auto' ? `Auto ? ${row.usb_product || 'USB serial adapter'} ? ${row.usb_serial_number || 'No serial number'}` : `Manual ? ${row.serial_port}` },
      { label: 'Enabled', render: (row) => row.enabled ? 'Yes' : 'No' },
      { label: 'Runtime', render: (row) => <ConnectionState id={row.id} auto={row.serial_port_mode === 'auto'} /> },
      { label: 'Transport test', render: (row) => <TestConnection id={row.id} name={row.name} /> },
    ]}
    editor={(row, save, cancel) => <EntityEditor<ConnectionInput> initial={row ? editable(row) : initial} onSave={save} onCancel={cancel}>
      {(value, change) => <>
        <TextInput label="Name" value={value.name} onChange={(next) => change('name', next)} required />
        <SelectInput label="Protocol" value={value.protocol} onChange={(next) => {
          const protocol = next as Protocol;
          change('protocol', protocol);
          change('serial_port_mode', 'manual'); change('usb_vid', null); change('usb_pid', null); change('usb_serial_number', null); change('usb_hardware_id', null); change('usb_manufacturer', null); change('usb_product', null); change('serial_probe_enabled', false);
          change('host', protocol === 'modbus_tcp' ? '' : null); change('port', protocol === 'modbus_tcp' ? 502 : null);
          change('serial_port', protocol === 'modbus_rtu' ? '' : null); change('baud_rate', protocol === 'modbus_rtu' ? 9600 : null);
          change('parity', protocol === 'modbus_rtu' ? 'N' : null); change('stop_bits', protocol === 'modbus_rtu' ? 1 : null); change('data_bits', protocol === 'modbus_rtu' ? 8 : null);
        }}>{choices(['modbus_tcp', 'modbus_rtu'])}</SelectInput>
        {value.protocol === 'modbus_tcp' ? <>
          <TextInput label="Host" value={value.host} onChange={(next) => change('host', next)} required helperText="IP address or hostname; no URL scheme or port." />
          <NumberInput label="Port" value={value.port} onChange={(next) => change('port', next)} required min={1} max={65535} />
        </> : <>
          <SelectInput label="Serial port mode" value={value.serial_port_mode ?? 'manual'} onChange={next => {
            change('serial_port_mode', next as 'manual' | 'auto'); change('serial_port', next === 'manual' ? '' : null);
            change('usb_vid', null); change('usb_pid', null); change('usb_serial_number', null); change('usb_hardware_id', null); change('usb_manufacturer', null); change('usb_product', null); change('serial_probe_enabled', false);
          }}><MenuItem value="manual">Manual</MenuItem><MenuItem value="auto">Auto detect</MenuItem></SelectInput>
          {value.serial_port_mode === 'auto' ? <>
            <Typography>Selected adapter: {value.usb_product || 'not selected'} ? VID {value.usb_vid?.toString(16).toUpperCase() ?? '?'} / PID {value.usb_pid?.toString(16).toUpperCase() ?? '?'} ? Serial {value.usb_serial_number || 'not provided'}</Typography>
            <AutoAdapter select={p => { change('usb_vid', p.vid ?? null); change('usb_pid', p.pid ?? null); change('usb_serial_number', p.serial_number || null); change('usb_hardware_id', p.hwid && p.hwid !== 'n/a' ? p.hwid : null); change('usb_manufacturer', p.manufacturer || null); change('usb_product', p.product || p.description); }} />
            <Toggle label="Allow read-only Modbus probe if ambiguous" value={value.serial_probe_enabled ?? false} onChange={next => change('serial_probe_enabled', next)} />
            <Typography variant="caption">Probing reads only configured enabled Tags/slaves, never writes. Matching device maps are evidence, not a unique hardware identity. If multiple adapters respond, binding is refused.</Typography>
          </> : <>
          <TextInput label="Serial port" value={value.serial_port} onChange={(next) => change('serial_port', next)} required helperText="Enter the port path/name visible to the worker. Docker may not expose host COM ports." />
          <SerialDiscovery select={(port) => change('serial_port', port)} />
          </>}
          <NumberInput label="Baud rate" value={value.baud_rate} onChange={(next) => change('baud_rate', next)} min={1} required />
          <SelectInput label="Parity" value={value.parity ?? ''} onChange={(next) => change('parity', next as ConnectionInput['parity'])} required>{choices(['N', 'E', 'O'])}</SelectInput>
          <SelectInput label="Stop bits" value={value.stop_bits ?? ''} onChange={(next) => change('stop_bits', Number(next))} required>{choices([1, 1.5, 2])}</SelectInput>
          <SelectInput label="Data bits" value={value.data_bits ?? ''} onChange={(next) => change('data_bits', Number(next))} required>{choices([7, 8])}</SelectInput>
        </>}
        <NumberInput label="Timeout (ms)" value={value.timeout_ms} onChange={(next) => change('timeout_ms', next ?? 0)} min={1} required />
        <Toggle label="Enabled" value={value.enabled} onChange={(next) => change('enabled', next)} />
      </>}
    </EntityEditor>} />;
}
