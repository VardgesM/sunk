import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '@mui/material';
import { describe, expect, it, vi } from 'vitest';
import { render } from './render';
import { appTheme } from '../layout/theme';
import UsersPage from '../pages/UsersPage';
import { usersApi, type User } from '../api/users';

const username = 'LongUnbrokenUsername_'.repeat(8);
const account: User = { id: 2, username, role: 'VIEWER', enabled: false, last_login_at: null, created_at: '', updated_at: '' };
function page() { return render(<ThemeProvider theme={appTheme}><UsersPage /></ThemeProvider>); }
async function actions() { await userEvent.click(await screen.findByRole('button', { name: `Actions for ${username}` })); }

describe('shared UI consistency and user actions', () => {
  it('distinguishes loading and an empty user page', async () => {
    let finish!: (rows: User[]) => void;
    vi.spyOn(usersApi, 'list').mockReturnValue(new Promise(resolve => { finish = resolve; }));
    page();
    expect(screen.getByRole('status')).toHaveTextContent('Loading users');
    expect(screen.queryByText('No users on this page.')).not.toBeInTheDocument();
    await act(async () => { finish([]); });
    expect(screen.getByText('No users on this page.')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
  it('preserves full long names, text statuses and compact labelled actions', async () => {
    vi.spyOn(usersApi, 'list').mockResolvedValue([account]);
    page();
    expect(await screen.findByRole('heading', { name: username })).toBeInTheDocument();
    expect(screen.getByText('VIEWER')).toBeInTheDocument();
    expect(screen.getByText('Disabled')).toBeInTheDocument();
    expect(screen.getByText('Last login: Never')).toBeInTheDocument();
    const edit = screen.getByRole('button', { name: `Edit ${username}` });
    expect(edit).toHaveTextContent(/^Edit$/);
    expect(getComputedStyle(edit).minHeight).toBe('44px');
    await actions();
    expect(screen.getByRole('menu', { name: `Actions for ${username}` })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Reset password' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.getByRole('button', { name: `Actions for ${username}` })).toHaveFocus());
  });
  it('keeps edit validation and the existing user API payload', async () => {
    vi.spyOn(usersApi, 'list').mockResolvedValue([account]);
    const edit = vi.spyOn(usersApi, 'edit').mockResolvedValue(account);
    page();
    await userEvent.click(await screen.findByRole('button', { name: `Edit ${username}` }));
    const dialog = screen.getByRole('dialog', { name: 'Edit user' });
    await userEvent.clear(within(dialog).getByLabelText('Username'));
    expect(within(dialog).getByRole('button', { name: 'Save user' })).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText('Username'), 'renamed');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save user' }));
    await waitFor(() => expect(edit).toHaveBeenCalledWith(2, { username: 'renamed', role: 'VIEWER', enabled: false }));
  });
  it('keeps deletion behind the existing confirmation and allows cancelling', async () => {
    vi.spyOn(usersApi, 'list').mockResolvedValue([account]);
    const remove = vi.spyOn(usersApi, 'remove').mockResolvedValue();
    page(); await actions();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }));
    let dialog = screen.getByRole('dialog', { name: `Delete ${username}?` });
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(remove).not.toHaveBeenCalled();
    await actions(); await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }));
    dialog = screen.getByRole('dialog', { name: `Delete ${username}?` });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(remove).toHaveBeenCalledExactlyOnceWith(2));
  });
  it('keeps password reset separate and clears the input on dismissal', async () => {
    vi.spyOn(usersApi, 'list').mockResolvedValue([account]);
    const reset = vi.spyOn(usersApi, 'reset').mockResolvedValue();
    page(); await actions(); await userEvent.click(screen.getByRole('menuitem', { name: 'Reset password' }));
    let dialog = screen.getByRole('dialog', { name: `Reset password for ${username}` });
    await userEvent.type(within(dialog).getByLabelText('New password'), 'discarded');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(reset).not.toHaveBeenCalled();
    await actions(); await userEvent.click(screen.getByRole('menuitem', { name: 'Reset password' }));
    dialog = screen.getByRole('dialog', { name: `Reset password for ${username}` });
    expect(within(dialog).getByLabelText('New password')).toHaveValue('');
    expect(within(dialog).getByRole('button', { name: 'Reset password' })).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText('New password'), 'test-password');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reset password' }));
    await waitFor(() => expect(reset).toHaveBeenCalledExactlyOnceWith(2, 'test-password'));
  });
  it('does not describe a loading failure as an empty page, and retains the full error', async () => {
    const message = 'LongServerError_'.repeat(50);
    vi.spyOn(usersApi, 'list').mockRejectedValue(new Error(message));
    page();
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByText('No users on this page.')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
