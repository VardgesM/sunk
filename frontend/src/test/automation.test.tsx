import { render, testAuth } from './render';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RuleEditor from '../components/RuleEditor';
import AutomationPage from '../pages/AutomationPage';
import { automationApi } from '../api/automation';
import { tagsApi } from '../api/configuration';
import type { Tag } from '../types/configuration';
import type { Rule } from '../types/automation';
import { AuthContext } from '../auth/context';
import * as commandsApi from '../api/commands';
import RuleCard from '../components/automation/RuleCard';
const tag: Tag = { id: 1, name: 'Reading', key: 'reading', device_id: 1, register_type: 'input_register', address: 0, data_type: 'uint16', byte_order: 'big', word_order: 'big', scale: 1, offset: 0, unit: null, poll_interval_ms: 1000, writable: false, enabled: true, history_enabled: false, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null, min_value: null, max_value: null, description: null, created_at: '', updated_at: '' };
const relay: Tag = { ...tag, id: 2, key: 'relay', name: 'Relay', data_type: 'bool', register_type: 'coil', writable: true };
const rule: Rule = { id: 1, name: 'Cooling', description: null, enabled: true, priority: 50, condition_mode: 'ALL', for_duration_ms: 2000, cooldown_ms: 60000, conditions: [{ tag_id: 1, operator: '>', value: '30', hysteresis: '2', sort_order: 0 }], actions: [{ target_tag_id: 2, kind: 'SET_TAG_VALUE', value: true, sort_order: 0 }], created_at: '', updated_at: '', runtime: { state: 'WAITING_FOR_DURATION', condition_state: true, true_since: null, cooldown_until: null, last_triggered_at: null, last_result: null, error: null } };

function viewport(width: number) {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: query.includes('min-width') ? width >= Number(query.match(/min-width:\s*([\d.]+)/)?.[1] ?? Infinity) : width <= Number(query.match(/max-width:\s*([\d.]+)/)?.[1] ?? 0),
    media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
}
function page(role: 'ADMIN' | 'OPERATOR' | 'VIEWER' = 'ADMIN') {
  const permissions = role === 'ADMIN' ? testAuth.user!.permissions : role === 'OPERATOR' ? ['read', 'command', 'acknowledge'] : ['read'];
  return render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, role, permissions } }}><MemoryRouter><AutomationPage /></MemoryRouter></AuthContext.Provider>);
}
beforeEach(() => {
  viewport(1440);
  vi.spyOn(tagsApi, 'all').mockResolvedValue([tag, relay]);
  vi.spyOn(automationApi, 'list').mockResolvedValue([rule]);
});

describe('automation editor', () => {
  it('adds and removes conditions/actions and submits typed values', async () => {
    const save = vi.fn().mockResolvedValue(undefined); const user = userEvent.setup();
    render(<RuleEditor tags={[tag, relay]} onSave={save} onClose={() => {}} />);
    await user.type(screen.getByLabelText(/Rule name/), 'New rule');
    await user.click(screen.getByRole('button', { name: 'Add condition' }));
    await user.click(screen.getByRole('button', { name: 'Add condition' }));
    await user.click(screen.getByRole('button', { name: 'Remove condition 2' }));
    await user.click(screen.getByRole('button', { name: 'Remove condition' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add condition' })).toHaveFocus());
    await user.clear(screen.getByLabelText(/Comparison 1/)); await user.type(screen.getByLabelText(/Comparison 1/), '30');
    await user.click(screen.getByRole('button', { name: 'Add action' }));
    await user.click(screen.getByRole('button', { name: 'Add action' }));
    await user.click(screen.getByRole('button', { name: 'Remove action 2' }));
    await user.click(screen.getByRole('button', { name: 'Remove action' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add action' })).toHaveFocus());
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
  it('keeps every existing field and typed precision when an edited rule is saved unchanged', async () => {
    const initial = { ...rule, description: 'Existing description', conditions: [{ ...rule.conditions[0], value: '18446744073709551615', sort_order: 4 }], actions: [{ ...rule.actions[0], sort_order: 9 }] };
    const save = vi.fn().mockResolvedValue(undefined);
    render(<RuleEditor initial={initial} tags={[tag, relay]} onSave={save} onClose={vi.fn()} />);
    expect(screen.getByRole('group', { name: '1. Basic information' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '2. When' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '3. Then' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '4. Execution behavior' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(initial));
  });
  it('preserves duration conversion and ALL/ANY API values', async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<RuleEditor initial={rule} tags={[tag, relay]} onSave={save} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('combobox', { name: 'Condition mode' }));
    await userEvent.click(screen.getByRole('option', { name: 'Any condition may match (ANY / OR)' }));
    await userEvent.clear(screen.getByLabelText('FOR seconds'));
    await userEvent.type(screen.getByLabelText('FOR seconds'), '5');
    await userEvent.clear(screen.getByLabelText('Cooldown seconds'));
    await userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ condition_mode: 'ANY', for_duration_ms: 5000, cooldown_ms: null })));
  });
  it('requires confirmation to remove a draft row and allows cancelling', async () => {
    const save = vi.fn();
    render(<RuleEditor initial={rule} tags={[tag, relay]} onSave={save} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove condition 1' }));
    expect(screen.getByRole('dialog', { name: 'Remove condition 1?' })).toHaveTextContent('only changes the draft');
    await userEvent.click(screen.getByRole('button', { name: 'Keep condition' }));
    expect(screen.getByRole('combobox', { name: 'Condition 1 Tag' })).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
  it('keeps unavailable action selections visible rather than silently replacing them', async () => {
    render(<RuleEditor initial={rule} tags={[tag, { ...relay, enabled: false }]} onSave={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: 'Action 1 Tag' })).toHaveTextContent('Relay (unavailable for new actions)');
    expect(screen.getByRole('button', { name: 'Add action' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Remove action 1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Remove action' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus());
  });
  it('uses a fullscreen mobile editor with accessible add/remove actions', () => {
    viewport(390);
    render(<RuleEditor initial={rule} tags={[tag, relay]} onSave={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('dialog')).toHaveClass('MuiDialog-paperFullScreen');
    expect(screen.getByRole('region', { name: 'Condition 1' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Action 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save rule' })).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: 'Actions for Cooling' }));
    await user.click(screen.getByRole('menuitem', { name: 'Disable rule' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(1, { enabled: false }));
    await user.click(screen.getByRole('button', { name: 'Executions' }));
    expect(await screen.findByText(/COMMANDS_CREATED/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '#42' })).toHaveAttribute('href', '/commands?command_id=42');
  });
  it.each(['ALL', 'ANY'] as const)('explains %s and renders conditions/actions using names, units and original order', async condition_mode => {
    vi.spyOn(tagsApi, 'all').mockResolvedValue([{ ...tag, unit: '%' }, relay]);
    vi.spyOn(automationApi, 'list').mockResolvedValue([{ ...rule, condition_mode, conditions: [...rule.conditions, { tag_id: 2, operator: '!=', value: false, hysteresis: '0', sort_order: 1 }], actions: [{ ...rule.actions[0], value: false }, { target_tag_id: 1, kind: 'SET_TAG_VALUE', value: '18446744073709551615', sort_order: 1 }] }]);
    page();
    const card = await screen.findByRole('article', { name: 'Cooling' });
    expect(within(card).getByText(condition_mode === 'ALL' ? 'All conditions must match:' : 'Any condition may match:')).toBeInTheDocument();
    expect(within(card).getByText('Reading > 30 %')).toBeInTheDocument();
    expect(within(card).getByText('Relay is not OFF')).toBeInTheDocument();
    expect(within(card).getByRole('region', { name: 'Then' }).textContent).toMatch(/Relay → OFF.*Reading → 18446744073709551615 %/);
  });
  it('explains IDLE and a never-triggered rule without displaying an error', async () => {
    vi.spyOn(automationApi, 'list').mockResolvedValue([{ ...rule, runtime: { ...rule.runtime!, state: 'IDLE', condition_state: false } }]);
    page();
    const card = await screen.findByRole('article', { name: 'Cooling' });
    expect(within(card).getByText('IDLE')).toBeInTheDocument();
    expect(within(card).getByText('Waiting for conditions')).toBeInTheDocument();
    expect(within(card).getByText('Last reported conditions: Not matched (FALSE)')).toBeInTheDocument();
    expect(within(card).getByText('Last triggered: Never')).toBeInTheDocument();
    expect(within(card).getByText('No execution result yet')).toBeInTheDocument();
    expect(within(card).queryByRole('alert')).not.toBeInTheDocument();
  });
  it('shows reported true state without evaluating telemetry in the browser', async () => {
    page();
    expect(await screen.findByText('Last reported conditions: Matched (TRUE)')).toBeInTheDocument();
    expect(screen.getByText('Waiting for the condition duration')).toBeInTheDocument();
  });
  it('does not invent IDLE or false when runtime is missing', async () => {
    vi.spyOn(automationApi, 'list').mockResolvedValue([{ ...rule, runtime: null }]);
    page();
    expect(await screen.findByText('Condition state unavailable')).toBeInTheDocument();
    expect(screen.getAllByText('Not reported').length).toBeGreaterThan(0);
    expect(screen.queryByText('IDLE')).not.toBeInTheDocument();
    expect(screen.queryByText(/Last reported conditions:/)).not.toBeInTheDocument();
  });
  it('does not treat retained condition truth during ERROR as a valid evaluation', async () => {
    vi.spyOn(automationApi, 'list').mockResolvedValue([{ ...rule, runtime: { ...rule.runtime!, state: 'ERROR', error: 'Condition input is disabled, stale, missing or not GOOD' } }]);
    page();
    expect(await screen.findByText('Condition state unavailable')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('stale, missing or not GOOD');
    expect(screen.queryByText(/Last reported conditions:/)).not.toBeInTheDocument();
  });
  it('clearly distinguishes disabled configuration from retained runtime', async () => {
    vi.spyOn(automationApi, 'list').mockResolvedValue([{ ...rule, enabled: false, runtime: { ...rule.runtime!, state: 'ACTIVE' } }]);
    page();
    expect(await screen.findByText('Disabled')).toBeInTheDocument();
    expect(screen.getByText('Rule is disabled')).toBeInTheDocument();
    expect(screen.getByText('Last reported runtime')).toBeInTheDocument();
    expect(screen.queryByText(/Last reported conditions:/)).not.toBeInTheDocument();
  });
  it.each([['SUCCESS', 'Last execution succeeded'], ['FAILED', 'Last execution failed'], ['PARTIAL_FAILURE', 'Some commands failed'], ['COMMANDS_CREATED', 'Commands created; awaiting results'], ['SKIPPED', 'Execution skipped']])('explains %s while retaining the original status', async (last_result, explanation) => {
    vi.spyOn(automationApi, 'list').mockResolvedValue([{ ...rule, runtime: { ...rule.runtime!, last_result } }]);
    page();
    expect(await screen.findByText(explanation)).toBeInTheDocument();
    expect(screen.getByText(last_result)).toBeInTheDocument();
  });
  it('wraps long names and lets users expand full backend error text', async () => {
    const name = 'Rule_'.repeat(50), error = 'Communication_details_'.repeat(50);
    vi.spyOn(automationApi, 'list').mockResolvedValue([{ ...rule, name, runtime: { ...rule.runtime!, state: 'ERROR', error } }]);
    page();
    expect(await screen.findByRole('heading', { name })).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Show full error' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(button);
    expect(screen.getByRole('button', { name: 'Collapse error' })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(error)).toBeInTheDocument();
  });
  it('filters loaded rules locally and resets filters without another API request', async () => {
    vi.spyOn(automationApi, 'list').mockResolvedValue([rule, { ...rule, id: 2, name: 'Heating', enabled: false, runtime: { ...rule.runtime!, state: 'DISABLED' } }]);
    page(); await screen.findByRole('article', { name: 'Cooling' });
    await userEvent.type(screen.getByLabelText('Search rules'), 'unknown');
    expect(screen.getByText('No rules match these filters.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Enabled filter' }));
    await userEvent.click(screen.getByRole('option', { name: 'Disabled' }));
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(screen.getByRole('article', { name: 'Heating' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Status filter' }));
    await userEvent.click(screen.getByRole('option', { name: 'WAITING_FOR_DURATION' }));
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(screen.getByRole('article', { name: 'Cooling' })).toBeInTheDocument();
    // Automatic three-second refresh is allowed; filtering never changes its arguments.
    expect(vi.mocked(automationApi.list).mock.calls.every(([signal]) => signal instanceof AbortSignal)).toBe(true);
  });
  it('keeps metadata failures visible and falls back to Tag IDs', async () => {
    vi.spyOn(tagsApi, 'all').mockRejectedValue(new Error('Metadata unavailable'));
    page();
    expect(await screen.findByText(/Tag names and units are unavailable/)).toBeInTheDocument();
    expect(screen.getByText('Tag #1 (name unavailable) > 30')).toBeInTheDocument();
  });
  it.each(['VIEWER', 'OPERATOR'] as const)('keeps %s read-only while allowing history', async role => {
    page(role);
    await screen.findByRole('article', { name: 'Cooling' });
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create rule' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Actions for Cooling' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Executions' })).toBeInTheDocument();
  });
  it('supports a labelled mobile menu and preserves explicit rule deletion confirmation', async () => {
    viewport(390);
    const remove = vi.spyOn(automationApi, 'remove').mockResolvedValue(undefined);
    page(); await screen.findByRole('article', { name: 'Cooling' });
    await userEvent.click(screen.getByRole('button', { name: 'Actions for Cooling' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete rule' }));
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(1));
  });
  it('shows a useful empty state without exposing configuration to a viewer', async () => {
    vi.spyOn(automationApi, 'list').mockResolvedValue([]);
    page('VIEWER');
    expect(await screen.findByText('No automation rules configured')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create rule' })).not.toBeInTheDocument();
  });
  it('does not enqueue commands when viewing or opening the editor', async () => {
    const send = vi.spyOn(commandsApi, 'createCommand');
    page(); await screen.findByRole('article', { name: 'Cooling' });
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Edit rule');
    expect(send).not.toHaveBeenCalled();
  });
  it('uses the unchanged complete rule PATCH when saving from the page', async () => {
    const update = vi.spyOn(automationApi, 'update').mockResolvedValue(rule);
    page(); await screen.findByRole('article', { name: 'Cooling' });
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    const expected = Object.fromEntries(Object.entries(rule).filter(([key]) => !['id', 'runtime', 'created_at', 'updated_at'].includes(key)));
    await waitFor(() => expect(update).toHaveBeenCalledWith(1, expected));
  });
  it('shows priority and original runtime fields only in details', async () => {
    render(<RuleCard rule={rule} tags={new Map([[1, tag], [2, relay]])} busy={false} onEdit={vi.fn()} onToggle={vi.fn()} onDelete={vi.fn()} onHistory={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(screen.getByText(/50 — higher priorities/)).toBeVisible();
    expect(screen.getByText('ALL')).toBeVisible();
  });
  it('renders history cards, snapshot metadata and full errors on mobile', async () => {
    viewport(360);
    const error = 'Failure detail '.repeat(50);
    vi.spyOn(automationApi, 'executions').mockResolvedValue([{ id: 1, rule_id: 1, triggered_at: '2026-01-01T00:00:00Z', completed_at: null, snapshot: [{ tag_id: 1, operator: '>', comparison: '30', value: '31', quality: 'GOOD' }], result: 'FAILED', error, command_ids: [42] }]);
    page(); await screen.findByRole('article', { name: 'Cooling' });
    await userEvent.click(screen.getByRole('button', { name: 'Executions' }));
    const card = await screen.findByRole('article', { name: 'Execution 1' });
    expect(screen.getByRole('dialog')).toHaveClass('MuiDialog-paperFullScreen');
    expect(within(card).getByText('Execution failed')).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Show full error' }));
    expect(within(card).getByText(error.trim())).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Condition snapshot' }));
    expect(within(card).getByText('Reading > 30')).toBeVisible();
    expect(within(card).getByText('Observed: 31')).toBeVisible();
    expect(within(card).getByRole('link', { name: '#42' })).toHaveAttribute('href', '/commands?command_id=42');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('distinguishes no executions from history API failure', async () => {
    vi.spyOn(automationApi, 'executions').mockRejectedValue(new Error('History unavailable'));
    page(); await screen.findByRole('article', { name: 'Cooling' });
    await userEvent.click(screen.getByRole('button', { name: 'Executions' }));
    expect(await screen.findByText('History unavailable')).toBeInTheDocument();
    expect(screen.queryByText(/No executions yet/)).not.toBeInTheDocument();
  });
});
