import { editable, connectionsApi } from '../api/configuration';
import EntityEditor from '../components/EntityEditor';
import { ConnectionState, TestConnection } from '../components/RuntimeStatus';
import SerialDiscovery from '../components/SerialDiscovery';
import ManagementPage from '../components/ManagementPage';
import { NumberInput, SelectInput, TextInput, Toggle } from '../components/ConfigurationFields';
import { choices } from '../components/choices';
import type { ConnectionInput, Protocol } from '../types/configuration';

const initial: ConnectionInput = {
  name: '', protocol: 'modbus_tcp', enabled: true, host: '', port: 502, timeout_ms: 1000,
  serial_port: null, baud_rate: null, parity: null, stop_bits: null, data_bits: null,
};

export default function ConnectionsPage() {
  return <ManagementPage title="Connections" api={connectionsApi}
    columns={[
      { label: 'Name', render: (row) => row.name },
      { label: 'Protocol', render: (row) => row.protocol === 'modbus_tcp' ? 'Modbus TCP' : 'Modbus RTU' },
      { label: 'Endpoint', render: (row) => row.protocol === 'modbus_tcp' ? `${row.host}:${row.port}` : row.serial_port },
      { label: 'Enabled', render: (row) => row.enabled ? 'Yes' : 'No' },
      { label: 'Runtime', render: (row) => <ConnectionState id={row.id} /> },
      { label: 'Transport test', render: (row) => <TestConnection id={row.id} name={row.name} /> },
    ]}
    editor={(row, save, cancel) => <EntityEditor<ConnectionInput> initial={row ? editable(row) : initial} onSave={save} onCancel={cancel}>
      {(value, change) => <>
        <TextInput label="Name" value={value.name} onChange={(next) => change('name', next)} required />
        <SelectInput label="Protocol" value={value.protocol} onChange={(next) => {
          const protocol = next as Protocol;
          change('protocol', protocol);
          change('host', protocol === 'modbus_tcp' ? '' : null); change('port', protocol === 'modbus_tcp' ? 502 : null);
          change('serial_port', protocol === 'modbus_rtu' ? '' : null); change('baud_rate', protocol === 'modbus_rtu' ? 9600 : null);
          change('parity', protocol === 'modbus_rtu' ? 'N' : null); change('stop_bits', protocol === 'modbus_rtu' ? 1 : null); change('data_bits', protocol === 'modbus_rtu' ? 8 : null);
        }}>{choices(['modbus_tcp', 'modbus_rtu'])}</SelectInput>
        {value.protocol === 'modbus_tcp' ? <>
          <TextInput label="Host" value={value.host} onChange={(next) => change('host', next)} required helperText="IP address or hostname; no URL scheme or port." />
          <NumberInput label="Port" value={value.port} onChange={(next) => change('port', next)} required min={1} max={65535} />
        </> : <>
          <TextInput label="Serial port" value={value.serial_port} onChange={(next) => change('serial_port', next)} required helperText="Enter the port path/name visible to the worker. Docker may not expose host COM ports." />
          <SerialDiscovery select={(port) => change('serial_port', port)} />
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
