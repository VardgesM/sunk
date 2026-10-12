import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { AuthContext, type AuthState } from '../auth/context';

vi.mock('../components/AlarmIndicator', () => ({ default: () => <span>Alarms: 0</span> }));
vi.mock('../components/HealthStatus', () => ({ default: () => <span>API available</span> }));
vi.mock('../components/RuntimeStatus', () => ({ SourceMode: () => <span>Source status</span> }));
vi.mock('../pages/DashboardsPage', () => ({ default: () => <h1>Dashboard page</h1> }));
vi.mock('../pages/TagsPage', () => ({ default: () => <h1>Tags page</h1> }));
vi.mock('../pages/TagDetailsPage', () => ({ default: () => <h1>Tag details page</h1> }));
vi.mock('../pages/HistoryPage', () => ({ default: () => <h1>History page</h1> }));
vi.mock('../pages/AlarmsPage', () => ({ default: () => <h1>Alarms page</h1> }));
vi.mock('../pages/CommandsPage', () => ({ default: () => <h1>Commands page</h1> }));
vi.mock('../pages/AutomationPage', () => ({ default: () => <h1>Automation page</h1> }));
vi.mock('../pages/LocationsPage', () => ({ default: () => <h1>Locations page</h1> }));
vi.mock('../pages/ConnectionsPage', () => ({ default: () => <h1>Connections page</h1> }));
vi.mock('../pages/DevicesPage', () => ({ default: () => <h1>Devices page</h1> }));
vi.mock('../pages/SystemPage', () => ({ default: () => <h1>System page</h1> }));
vi.mock('../pages/UsersPage', () => ({ default: () => <h1>Users page</h1> }));
vi.mock('../pages/AuditPage', () => ({ default: () => <h1>Audit page</h1> }));
vi.mock('../pages/BackupRestorePage', () => ({ default: () => <h1>Backup & Restore page</h1> }));
vi.mock('../pages/UpdatesPage', () => ({ default: () => <h1>Updates page</h1> }));

const state: AuthState = {
  user: { id: 1, username: 'administrator_with_a_long_name', role: 'ADMIN', permissions: ['read', 'configure', 'users', 'audit', 'command'] },
  loading: false, login: async () => {}, logout: async () => {}, refresh: async () => {},
};
function viewport(width: number) {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: width >= Number(query.match(/min-width:\s*(\d+)/)?.[1] ?? Infinity),
    media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })));
}
function Back() { const navigate = useNavigate(); return <button onClick={() => navigate(-1)}>Browser back</button>; }
function show(path = '/dashboard', auth = state, entries = [path]) {
  return render(<ThemeProvider theme={createTheme()}><CssBaseline /><MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
    <AuthContext.Provider value={auth}><App /><Back /></AuthContext.Provider>
  </MemoryRouter></ThemeProvider>);
}
beforeEach(() => { viewport(1440); vi.stubGlobal('scrollTo', vi.fn()); });

describe('responsive application navigation', () => {
  it('groups desktop destinations without duplicating routes', async () => {
    show();
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    for (const name of ['Overview', 'Monitoring', 'Control', 'Configuration', 'System']) expect(within(nav).getByRole('region', { name })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open navigation' })).not.toBeInTheDocument();
    expect(within(nav).getAllByRole('link')).toHaveLength(14);
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page');
    await userEvent.click(within(nav).getByRole('link', { name: 'Tags' }));
    expect(await screen.findByRole('heading', { name: 'Tags page' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('main', { name: 'Tags' })).toHaveFocus());
    expect(document.title).toBe('Tags | Modbus Monitor');
  });
  it.each([360, 390, 768, 1024])('uses a closed drawer at %dpx and closes it after navigation', async width => {
    viewport(width); show();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    const trigger = screen.getByRole('button', { name: 'Open navigation' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(trigger);
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    await userEvent.click(within(nav).getByRole('link', { name: 'Backup & Restore' }));
    expect(await screen.findByRole('heading', { name: 'Backup & Restore page' })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('navigation')).not.toBeInTheDocument());
    expect(within(screen.getByRole('banner')).getByText('Backup & Restore')).toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });
  it('dismisses on Escape and restores focus to the menu trigger', async () => {
    viewport(390); show();
    const trigger = screen.getByRole('button', { name: 'Open navigation' });
    await userEvent.click(trigger); await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('navigation')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
  it('closes when selecting the already active mobile destination', async () => {
    viewport(360); show();
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    await userEvent.click(screen.getByRole('link', { name: 'Dashboard' }));
    await waitFor(() => expect(screen.queryByRole('navigation')).not.toBeInTheDocument());
  });
  it('highlights Tags for detail URLs and the exact nested System destination', async () => {
    show('/tags/42');
    expect(screen.getByRole('link', { name: 'Tags' })).toHaveAttribute('aria-current', 'page');
    expect(within(screen.getByRole('banner')).getByText('Tag details')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: 'Updates' }));
    await screen.findByRole('heading', { name: 'Updates page' });
    expect(screen.getByRole('link', { name: 'Updates' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'System' })).not.toHaveAttribute('aria-current');
  });
  it('updates the title on browser back', async () => {
    show('/tags', state, ['/dashboard', '/tags']);
    await userEvent.click(screen.getByRole('button', { name: 'Browser back' }));
    expect(await screen.findByRole('heading', { name: 'Dashboard page' })).toBeInTheDocument();
    expect(within(screen.getByRole('banner')).getByText('Dashboard')).toBeInTheDocument();
  });
  it('recognizes trailing slashes and keeps the root redirect', async () => {
    show('/');
    expect(await screen.findByRole('heading', { name: 'Dashboard page' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page');
  });
  it('marks a route with a trailing slash active', async () => {
    show('/settings/backups/');
    expect(await screen.findByRole('heading', { name: 'Backup & Restore page' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Backup & Restore' })).toHaveAttribute('aria-current', 'page');
    expect(within(screen.getByRole('banner')).getByText('Backup & Restore')).toBeInTheDocument();
  });
  it.each(['VIEWER', 'OPERATOR', 'ADMIN'] as const)('preserves %s navigation permissions', role => {
    show('/dashboard', { ...state, user: { ...state.user!, role, permissions: role === 'ADMIN' ? state.user!.permissions : ['read', ...(role === 'OPERATOR' ? ['command', 'acknowledge'] : [])] } });
    for (const name of ['Users', 'Audit', 'Backup & Restore', 'Updates']) expect(screen.queryByRole('link', { name }) !== null).toBe(role === 'ADMIN');
    for (const name of ['Dashboard', 'Tags', 'History', 'Devices', 'Alarms', 'Commands', 'Automation', 'System']) expect(screen.getByRole('link', { name })).toBeInTheDocument();
  });
  it.each(['/users', '/audit', '/settings/backups', '/settings/updates'])('keeps direct ADMIN route %s protected', async path => {
    show(path, { ...state, user: { ...state.user!, role: 'VIEWER', permissions: ['read'] } });
    await act(async () => {});
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument();
  });
  it.each([
    ['/history', 'History'],
    ['/dashboard', 'Dashboard'], ['/locations', 'Locations'], ['/connections', 'Connections'], ['/devices', 'Devices'], ['/tags', 'Tags'], ['/tags/42', 'Tag details'], ['/commands', 'Commands'], ['/automation', 'Automation'], ['/alarms', 'Alarms'], ['/users', 'Users'], ['/audit', 'Audit'], ['/settings', 'System'], ['/settings/backups', 'Backup & Restore'], ['/settings/updates', 'Updates'],
  ])('preserves the existing %s route', async (path, title) => {
    show(path);
    expect(await screen.findByRole('heading', { name: `${title} page` })).toBeInTheDocument();
    expect(within(screen.getByRole('banner')).getByText(title)).toBeInTheDocument();
  });
  it('keeps logout and password controls accessible from the compact account menu', async () => {
    viewport(360); const logout = vi.fn().mockResolvedValue(undefined); show('/dashboard', { ...state, logout });
    await userEvent.click(screen.getByRole('button', { name: /Account:/ }));
    expect(screen.getByRole('menu', { name: 'Account menu' })).toHaveTextContent(state.user!.username);
    await userEvent.click(screen.getByRole('menuitem', { name: 'Change password' }));
    expect(screen.getByRole('dialog', { name: 'Change password' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await userEvent.click(await screen.findByRole('button', { name: /Account:/ }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Logout' }));
    expect(logout).toHaveBeenCalledOnce();
  });
  it('provides a keyboard skip link', async () => {
    show(); await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByRole('main')).toHaveFocus();
  });
});
