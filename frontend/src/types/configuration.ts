export type Protocol = 'modbus_rtu' | 'modbus_tcp';
export type RegisterType = 'coil' | 'discrete_input' | 'input_register' | 'holding_register';
export type DataType = 'bool' | 'uint16' | 'int16' | 'uint32' | 'int32' | 'float32' | 'uint64' | 'int64' | 'float64';
export type Order = 'big' | 'little';
export type HistoryMode = 'every_sample' | 'fixed_interval' | 'on_change';

export interface Entity { id: number; name: string; created_at: string; updated_at: string }
export interface Location extends Entity {
  parent_id: number | null; description: string | null; sort_order: number;
}
export interface Connection extends Entity {
  serial_port_mode?: 'manual' | 'auto'; usb_vid?: number | null; usb_pid?: number | null;
  usb_serial_number?: string | null; usb_hardware_id?: string | null;
  usb_manufacturer?: string | null; usb_product?: string | null; serial_probe_enabled?: boolean;
  protocol: Protocol; enabled: boolean; serial_port: string | null;
  baud_rate: number | null; parity: 'N' | 'E' | 'O' | null;
  stop_bits: number | null; data_bits: number | null; host: string | null;
  port: number | null; timeout_ms: number;
}
export interface Device extends Entity {
  connection_id: number; location_id: number | null; slave_id: number;
  enabled: boolean; description: string | null; connection_protocol: Protocol;
}
export interface Tag extends Entity {
  key: string; device_id: number; register_type: RegisterType; address: number;
  data_type: DataType; byte_order: Order; word_order: Order; scale: number; offset: number;
  unit: string | null; poll_interval_ms: number; writable: boolean; history_enabled: boolean;
  history_mode: HistoryMode; history_interval_ms: number | null;
  history_change_threshold: number | null; history_retention_days: number | null;
  enabled: boolean; min_value: number | null; max_value: number | null; description: string | null;
}
export type Input<T extends Entity> = Omit<T, 'id' | 'created_at' | 'updated_at' | 'connection_protocol'>;
export type LocationInput = Input<Location>;
export type ConnectionInput = Input<Connection>;
export type DeviceInput = Input<Device>;
export type TagInput = Input<Tag>;
