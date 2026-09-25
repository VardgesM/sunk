import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { LiveConnectionStatus, LiveValue } from '../components/LiveValues';

vi.mock('../hooks/useLiveValues', () => ({
  useLiveStatus: () => ({ state: 'Reconnecting', error: 'Waiting for PostgreSQL live updates' }),
  useTagValue: () => ({ quality: 'COMM_ERROR', error: 'Simulated communication failure', value_numeric: null, value_boolean: false, value_text: null }),
}));

it('communicates quality and connection loss in text and preserves false values', () => {
  render(<><LiveConnectionStatus /><LiveValue tagId={1} field="quality" /><LiveValue tagId={1} field="value" /></>);
  expect(screen.getByText('Reconnecting')).toBeInTheDocument();
  expect(screen.getByText('COMM_ERROR')).toBeInTheDocument();
  expect(screen.getByText('False')).toBeInTheDocument();
  expect(screen.getByText('Waiting for PostgreSQL live updates')).toBeInTheDocument();
});
