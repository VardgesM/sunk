import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import RuleEditor from '../components/RuleEditor';
import AutomationPage from '../pages/AutomationPage';
import { automationApi } from '../api/automation';
import { tagsApi } from '../api/configuration';
import type { Tag } from '../types/configuration';
import type { Rule } from '../types/automation';
const tag: Tag = { id: 1, name: 'Reading', key: 'reading', device_id: 1, register_type: 'input_register', address: 0, data_type: 'uint16', byte_order: 'big', word_order: 'big', scale: 1, offset: 0, unit: null, poll_interval_ms: 1000, writable: false, enabled: true, history_enabled: false, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null, min_value: null, max_value: null, description: null, created_at: '', updated_at: '' };
const relay: Tag = { ...tag, id: 2, key: 'relay', name: 'Relay', data_type: 'bool', register_type: 'coil', writable: true };
const rule: Rule = { id: 1, name: 'Cooling', description: null, enabled: true, priority: 50, condition_mode: 'ALL', for_duration_ms: 2000, cooldown_ms: 60000, conditions: [{ tag_id: 1, operator: '>', value: '30', hysteresis: '2', sort_order: 0 }], actions: [{ target_tag_id: 2, kind: 'SET_TAG_VALUE', value: true, sort_order: 0 }], created_at: '', updated_at: '', runtime: { state: 'WAITING_FOR_DURATION', condition_state: true, true_since: null, cooldown_until: null, last_triggered_at: null, last_result: null, error: null } };

describe('automation editor', () => {
  it('adds and removes conditions/actions and submits typed values', async () => {
    const save = vi.fn().mockResolvedValue(undefined); const user = userEvent.setup();
    render(<RuleEditor tags={[tag, relay]} onSave={save} onClose={() => {}} />);
    await user.type(screen.getByLabelText(/Rule name/), 'New rule');
    await user.click(screen.getByRole('button', { name: 'Add condition' }));
    await user.click(screen.getByRole('button', { name: 'Add condition' }));
    await user.click(screen.getByRole('button', { name: 'Remove condition 2' }));
    await user.clear(screen.getByLabelText(/Comparison 1/)); await user.type(screen.getByLabelText(/Comparison 1/), '30');
    await user.click(screen.getByRole('button', { name: 'Add action' }));
    await user.click(screen.getByRole('button', { name: 'Add action' }));
    await user.click(screen.getByRole('button', { name: 'Remove action 2' }));
    await user.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ name: 'New rule', conditions: [expect.objectContaining({ tag_id: 1, value: '30' })], actions: [expect.objectContaining({ target_tag_id: 2, value: false })] })));
  });
  it('shows validation for an empty rule', async () => {
    const save = vi.fn(); const user = userEvent.setup();
    render(<RuleEditor tags={[tag]} onSave={save} onClose={() => {}} />);
    await user.type(screen.getByLabelText(/Rule name/), 'Empty');
    await user.click(screen.getByRole('button', { name: 'Save rule' }));
    expect(await screen.findByText('Add at least one condition and action')).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled(); expect(screen.getByRole('button', { name: 'Add action' })).toBeDisabled();
  });
  it('displays server validation errors without closing the editor', async () => {
    const user = userEvent.setup(); render(<RuleEditor initial={rule} tags={[tag, relay]} onSave={vi.fn().mockRejectedValue(new Error('Target disabled'))} onClose={() => {}} />);
    await user.click(screen.getByRole('button', { name: 'Save rule' }));
    expect(await screen.findByText('Target disabled')).toBeInTheDocument();
  });
  it('uses boolean comparisons without numeric hysteresis controls', () => {
    render(<RuleEditor initial={{ ...rule, conditions: [{ tag_id: 2, operator: '==', value: true, hysteresis: '0', sort_order: 0 }] }} tags={[tag, relay]} onSave={vi.fn()} onClose={() => {}} />);
    expect(screen.queryByLabelText('Hysteresis 1')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Comparison 1/ })).toHaveTextContent('ON / true');
  });
});

describe('automation status and executions', () => {
  it('shows runtime, toggles enabled state and opens execution history', async () => {
    vi.spyOn(tagsApi, 'all').mockResolvedValue([tag, relay]);
    vi.spyOn(automationApi, 'list').mockResolvedValue([rule]);
    const update = vi.spyOn(automationApi, 'update').mockResolvedValue({ ...rule, enabled: false });
    vi.spyOn(automationApi, 'executions').mockResolvedValue([{ id: 1, rule_id: 1, triggered_at: '2026-01-01T00:00:00Z', completed_at: null, snapshot: [{ tag_id: 1, operator: '>', comparison: '30', value: '31', quality: 'GOOD' }], result: 'COMMANDS_CREATED', error: null, command_ids: [42] }]);
    const user = userEvent.setup(); render(<MemoryRouter><AutomationPage /></MemoryRouter>);
    expect(await screen.findByText('WAITING_FOR_DURATION')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Disable' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(1, { enabled: false }));
    await user.click(screen.getByRole('button', { name: 'Executions' }));
    expect(await screen.findByText(/COMMANDS_CREATED/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '#42' })).toHaveAttribute('href', '/commands?command_id=42');
  });
});
