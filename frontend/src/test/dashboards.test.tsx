import { render as renderWithAuth, testAuth } from './render';
import { MemoryRouter } from 'react-router-dom';
import { AuthContext } from '../auth/context';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement, ReactNode } from 'react';
import type { ResponsiveLayouts } from 'react-grid-layout';
import type { Tag } from '../types/configuration';
import type { Widget, DashboardDetail, Breakpoint } from '../types/dashboards';
import type { CurrentValue } from '../types/telemetry';
import DashboardsPage from '../pages/DashboardsPage';
import WidgetEditor from '../components/WidgetEditor';
import DashboardWidget from '../widgets/DashboardWidget';
import ChartWidget from '../widgets/ChartWidget';
import { dashboardsApi } from '../api/dashboards';
import { tagsApi } from '../api/configuration';
import { alarmsApi } from '../api/alarms';
import * as historyApi from '../api/history';
import { liveStore } from '../websocket/liveStore';
import * as client from '../api/client';
import DashboardConnectivity from '../widgets/DashboardConnectivity';
import * as commandsApi from '../api/commands';

const render = (ui: ReactElement) => renderWithAuth(<MemoryRouter>{ui}</MemoryRouter>);

const chart = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }));
const grid = vi.hoisted(() => ({ width: 390, render: vi.fn() }));
vi.mock('echarts/core', () => ({ init: () => chart, use: vi.fn() }));
vi.mock('react-grid-layout', () => ({
  useContainerWidth: () => ({ width: grid.width, mounted: true, containerRef: { current: null } }),
  Responsive: ({ children, layouts, onLayoutChange, onDragStop, dragConfig }: { children: ReactNode; layouts: ResponsiveLayouts<Breakpoint>; onLayoutChange: (l: never[], all: ResponsiveLayouts<Breakpoint>) => void; onDragStop: () => void; dragConfig: {enabled: boolean} }) => {
    grid.render(layouts);
    return <div data-testid="grid">{children}{dragConfig.enabled && <button onClick={() => { onLayoutChange([], { ...layouts, sm: layouts.sm?.map(l => ({ ...l, y: 3 })) }); onDragStop(); }}>Move test widget</button>}</div>;
  },
}));
const tag: Tag = { id: 1, name: 'Reading', key: 'reading', device_id: 1, register_type: 'input_register', address: 0, data_type: 'float32', byte_order: 'big', word_order: 'big', scale: 1, offset: 0, unit: 'C', poll_interval_ms: 1000, writable: false, enabled: true, history_enabled: true, history_mode: 'every_sample', history_interval_ms: null, history_change_threshold: null, history_retention_days: null, min_value: null, max_value: null, description: null, created_at: '', updated_at: '' };
const relay: Tag = { ...tag, id: 2, name: 'Relay', key: 'relay', data_type: 'bool', register_type: 'coil', writable: true, unit: null };
const widget: Widget = { id: 1, dashboard_id: 1, type: 'value', title: 'Live reading', configuration: {}, tag_ids: [1], layouts: [{ breakpoint: 'lg', x: 0, y: 0, w: 4, h: 6 }, { breakpoint: 'md', x: 0, y: 0, w: 3, h: 6 }, { breakpoint: 'sm', x: 0, y: 0, w: 1, h: 6 }], created_at: '', updated_at: '' };
const board: DashboardDetail = { id: 1, name: 'Overview', slug: 'overview', description: null, is_default: true, revision: 1, created_at: '', updated_at: '', widgets: [widget] };
const value: CurrentValue = { tag_id: 1, key: 'reading', name: 'Reading', device_id: 1, data_type: 'float32', unit: 'C', enabled: true, effective_enabled: true, value_numeric: 24.6, value_numeric_exact: '24.6', value_boolean: null, value_text: null, raw_value: null, quality: 'GOOD', source_timestamp: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', error: null, revision: 1 };

beforeEach(() => {
  grid.width = 390; grid.render.mockClear();
  vi.spyOn(alarmsApi, 'summary').mockResolvedValue({ active: 0, critical: 0 });
  vi.spyOn(liveStore,'retain').mockReturnValue(() => {});
  vi.spyOn(liveStore,'getValue').mockReturnValue(value);
  vi.spyOn(dashboardsApi,'all').mockResolvedValue([board]);
  vi.spyOn(dashboardsApi,'get').mockResolvedValue(board);
  vi.spyOn(tagsApi,'all').mockResolvedValue([tag,relay]);
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  chart.setOption.mockClear();
});

describe('dashboard builder', () => {
  it('derives mobile alarm-first order without changing or saving existing layouts', async () => {
    const alarm = { ...widget, id: 2, type: 'alarms' as const, title: 'Important alarms', tag_ids: [], layouts: widget.layouts.map(l => ({ ...l, y: 20 })) };
    const original = { ...board, widgets: [widget, alarm] };
    vi.spyOn(dashboardsApi, 'get').mockResolvedValue(original);
    vi.spyOn(alarmsApi, 'events').mockResolvedValue([]);
    const save = vi.spyOn(dashboardsApi, 'layout');
    render(<DashboardsPage />);
    await screen.findByRole('article', { name: 'Live reading' });
    expect(screen.getAllByRole('article').map(el => el.getAttribute('aria-label'))).toEqual(['Important alarms', 'Live reading']);
    expect(screen.queryByTestId('grid')).not.toBeInTheDocument();
    expect(original.widgets[1].layouts[0].y).toBe(20);
    expect(save).not.toHaveBeenCalled();
  });
  it.each([720, 976, 1112])('keeps saved table/desktop grid positions at container width %i', async width => {
    grid.width = width;
    render(<DashboardsPage />);
    await screen.findByTestId('grid');
    expect(grid.render).toHaveBeenLastCalledWith(expect.objectContaining({ lg: [expect.objectContaining({ x: 0, y: 0, w: 4, h: 6 })], md: [expect.objectContaining({ w: 3 })] }));
    expect(screen.queryByRole('button', { name: 'Move test widget' })).not.toBeInTheDocument();
  });
  it('switches viewing widths without persisting derived mobile layout', async () => {
    const save = vi.spyOn(dashboardsApi, 'layout');
    const { rerender } = render(<DashboardsPage />);
    await screen.findByRole('article', { name: 'Live reading' });
    grid.width = 1100;
    rerender(<MemoryRouter><DashboardsPage /></MemoryRouter>);
    expect(await screen.findByTestId('grid')).toBeInTheDocument();
    grid.width = 328;
    rerender(<MemoryRouter><DashboardsPage /></MemoryRouter>);
    expect(screen.queryByTestId('grid')).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
  it('retains long titles and configuration errors in individual cards', async () => {
    const title = 'Long_unbroken_widget_name_'.repeat(10);
    vi.spyOn(dashboardsApi, 'get').mockResolvedValue({ ...board, widgets: [{ ...widget, title, tag_ids: [999] }] });
    render(<DashboardsPage />);
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
    expect(screen.getByRole('article', { name: title })).toHaveTextContent('referenced Tag is missing');
  });
  it('offers the existing builder action on an empty configured dashboard', async () => {
    vi.spyOn(dashboardsApi, 'get').mockResolvedValue({ ...board, widgets: [] });
    render(<DashboardsPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add first widget' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Add widget');
  });
  it.each(['VIEWER', 'OPERATOR'] as const)('shows a permission-aware empty state for %s', async role => {
    vi.spyOn(dashboardsApi, 'get').mockResolvedValue({ ...board, widgets: [] });
    render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, role, permissions: ['read'] } }}><DashboardsPage /></AuthContext.Provider>);
    expect(await screen.findByText('An administrator can add widgets to this dashboard.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add first widget' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create dashboard' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit dashboard layout' })).not.toBeInTheDocument();
  });
  it.each(['STALE', 'COMM_ERROR', 'BAD', 'DISABLED'] as const)('always identifies %s retained values even when quality is hidden in settings', quality => {
    vi.spyOn(liveStore, 'getValue').mockReturnValue({ ...value, quality });
    render(<DashboardWidget widget={{ ...widget, type: 'gauge', configuration: { show_quality: false } }} tags={new Map([[1, tag]])} editing={false} />);
    expect(screen.getByText(quality)).toBeInTheDocument();
    expect(screen.getByText(/Last known value/)).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.getByLabelText('24.60 C')).toBeInTheDocument();
  });
  it('shows unavailable telemetry without inventing a value', () => {
    vi.spyOn(liveStore, 'getValue').mockReturnValue(undefined);
    render(<DashboardWidget widget={widget} tags={new Map([[1, tag]])} editing={false} />);
    expect(screen.getByText(/No current value/)).toBeInTheDocument();
  });
  it('preserves viewer read-only control and alarm permissions', async () => {
    vi.spyOn(client, 'request').mockResolvedValue({ mode: 'simulator', alive: true } as never);
    vi.spyOn(commandsApi, 'getCommands').mockResolvedValue([]);
    render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, role: 'VIEWER', permissions: ['read'] } }}><DashboardWidget widget={{ ...widget, type: 'switch', tag_ids: [2] }} tags={new Map([[2, relay]])} editing={false} /></AuthContext.Provider>);
    expect(screen.getByText('Read-only access')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument();
  });
  it('keeps operator controls on the existing confirmed command path', async () => {
    vi.spyOn(client, 'request').mockResolvedValue({ mode: 'simulator', alive: true } as never);
    vi.spyOn(commandsApi, 'getCommands').mockResolvedValue([]);
    const send = vi.spyOn(commandsApi, 'createCommand').mockRejectedValue(new Error('Fixture: no command was sent'));
    render(<AuthContext.Provider value={{ ...testAuth, user: { ...testAuth.user!, role: 'OPERATOR', permissions: ['read', 'command'] } }}><DashboardWidget widget={{ ...widget, type: 'switch', tag_ids: [2] }} tags={new Map([[2, relay]])} editing={false} /></AuthContext.Provider>);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Confirm simulated write');
    expect(send).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm write' }));
    await waitFor(() => expect(send).toHaveBeenCalledWith(2, false, expect.any(String), false));
  });
  it('creates a dashboard from the empty state', async () => {
    vi.spyOn(dashboardsApi,'all').mockResolvedValue([]);
    const create = vi.spyOn(dashboardsApi,'create').mockResolvedValue(board);
    const user = userEvent.setup(); render(<DashboardsPage />);
    expect(await screen.findByText(/No dashboards yet/)).toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'Create dashboard'}));
    await user.type(screen.getByLabelText(/Dashboard name/),'Overview'); await user.type(screen.getByLabelText(/Slug/),'overview');
    await user.click(screen.getByRole('button',{name:'Save dashboard'}));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({name:'Overview',slug:'overview'})));
  });
  it('loads the default dashboard and locks normal-mode layout', async () => {
    render(<DashboardsPage />); expect(await screen.findByText('Live reading')).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Move test widget'})).not.toBeInTheDocument();
    expect(tagsApi.all).toHaveBeenCalledTimes(1);
  });
  it('saves a phone layout only on explicit save', async () => {
    const save = vi.spyOn(dashboardsApi,'layout').mockResolvedValue({...board,revision:2});
    const user = userEvent.setup(); render(<DashboardsPage />); await screen.findByText('Live reading');
    await user.click(screen.getByRole('button',{name:'Edit dashboard layout'}));
    await user.click(screen.getByRole('button',{name:'Move test widget'})); expect(save).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button',{name:'Save layout'}));
    await waitFor(() => expect(save).toHaveBeenCalledWith(1,1,expect.arrayContaining([{widget_id:1,breakpoint:'sm',x:0,y:3,w:1,h:6}])));
  });
  it('edits and removes a widget with confirmation', async () => {
    const edit = vi.spyOn(dashboardsApi,'editWidget').mockResolvedValue(widget);
    const remove = vi.spyOn(dashboardsApi,'removeWidget').mockResolvedValue(undefined);
    const user = userEvent.setup(); render(<DashboardsPage />); await screen.findByText('Live reading');
    await user.click(screen.getByRole('button',{name:'Edit dashboard layout'}));
    await user.click(screen.getByRole('button',{name:'Edit Live reading'}));
    await user.click(screen.getByRole('button',{name:'Save widget'}));
    await waitFor(() => expect(edit).toHaveBeenCalled());
    await user.click(screen.getByRole('button',{name:'Remove Live reading'})); expect(remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button',{name:'Remove widget'})); await waitFor(() => expect(remove).toHaveBeenCalledWith(1));
  });
  it('adds a text widget through the builder', async () => {
    const add = vi.spyOn(dashboardsApi,'addWidget').mockResolvedValue(widget);
    const user = userEvent.setup(); render(<DashboardsPage />); await screen.findByText('Live reading');
    await user.click(screen.getByRole('button',{name:'Edit dashboard layout'})); await user.click(screen.getByRole('button',{name:'Add widget'}));
    await user.click(screen.getByRole('combobox',{name:'Widget type'})); await user.click(screen.getByRole('option',{name:'Text / Label'}));
    await user.type(screen.getByLabelText(/Widget title/),'Instructions'); await user.type(screen.getByLabelText('Text'),'Read only test');
    await user.click(screen.getByRole('button',{name:'Save widget'}));
    await waitFor(() => expect(add).toHaveBeenCalledWith(1,expect.objectContaining({type:'text',tag_ids:[],configuration:{text:'Read only test'}})));
  });
  it('filters switch Tags and displays server validation', async () => {
    const save = vi.fn().mockRejectedValue(new Error('Tag is disabled'));
    const user = userEvent.setup(); render(<WidgetEditor initial={{...widget,type:'switch',tag_ids:[2]}} tags={[tag,relay]} nextY={0} onSave={save} onClose={() => {}} />);
    await user.click(screen.getByRole('combobox',{name:'Tag'}));
    expect(screen.queryByRole('option',{name:/Reading/})).not.toBeInTheDocument();
    await user.click(screen.getByRole('option',{name:/Relay/})); await user.click(screen.getByRole('button',{name:'Save widget'}));
    expect(await screen.findByText('Tag is disabled')).toBeInTheDocument();
  });
  it('updates only the subscribed live value and shows quality errors', async () => {
    let update = () => {};
    vi.spyOn(liveStore,'subscribe').mockImplementation((_id,callback) => { update=callback; return () => {}; });
    const get = vi.spyOn(liveStore,'getValue').mockReturnValue(value);
    render(<DashboardWidget widget={widget} tags={new Map([[1,tag]])} editing={false} />);
    expect(screen.getByLabelText('24.60 C')).toBeInTheDocument();
    get.mockReturnValue({...value,value_numeric:25.2,quality:'COMM_ERROR',error:'Timeout',revision:2});
    act(() => update());
    expect(screen.getByLabelText('25.20 C')).toBeInTheDocument(); expect(screen.getByText('Timeout')).toBeInTheDocument();
  });
  it('renders gauge thresholds and boolean labels without relying on color', () => {
    const {rerender} = render(<DashboardWidget widget={{...widget,type:'gauge',configuration:{warning_threshold:20}}} tags={new Map([[1,tag]])} editing={false} />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow','25'); expect(screen.getByText('Warning range')).toBeInTheDocument();
    vi.spyOn(liveStore,'getValue').mockReturnValue({...value,value_boolean:false,value_numeric:null});
    rerender(<DashboardWidget widget={{...widget,type:'boolean',tag_ids:[2],configuration:{off_label:'Stopped'}}} tags={new Map([[2,relay]])} editing={false} />);
    expect(screen.getByText('Stopped')).toBeInTheDocument();
  });
  it('isolates missing Tag and changed control configuration errors', () => {
    const {rerender} = render(<DashboardWidget widget={widget} tags={new Map()} editing={false} />);
    expect(screen.getByText(/Tag is missing/)).toBeInTheDocument();
    rerender(<DashboardWidget widget={{...widget,type:'switch'}} tags={new Map([[1,tag]])} editing={false} />);
    expect(screen.getByText(/Control unavailable/)).toBeInTheDocument();
  });
  it('disables controls during editing', () => {
    render(<DashboardWidget widget={{...widget,type:'switch',tag_ids:[2]}} tags={new Map([[2,relay]])} editing />);
    expect(screen.getByText(/Controls are unavailable while editing/)).toBeInTheDocument();
  });
  it('shows alarms and uses the existing acknowledge API', async () => {
    vi.spyOn(alarmsApi,'events').mockResolvedValue([{id:1,rule_id:1,tag_id:1,name:'High',tag_name:'Reading',unit:'C',condition:'> 30',severity:'CRITICAL',state:'ACTIVE',value_numeric:'31',value_boolean:null,activated_at:'2026-09-01T00:00:00Z',acknowledged_at:null,cleared_at:null,clear_reason:null,revision:1}]);
    const ack = vi.spyOn(alarmsApi,'acknowledge').mockResolvedValue({} as never);
    render(<DashboardWidget widget={{...widget,type:'alarms',tag_ids:[],configuration:{severities:['CRITICAL']}}} tags={new Map()} editing={false} />);
    expect(await screen.findByRole('region', { name: 'CRITICAL: High' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'Acknowledge'})); await waitFor(() => expect(ack).toHaveBeenCalledWith(1));
  });
  it('renders multiple numeric history series and preserves invalid-quality gaps', async () => {
    vi.spyOn(historyApi,'getHistory').mockImplementation(async id => ({
      tag:{id,key:`tag_${id}`,name:`Tag ${id}`,unit:'C',data_type:'float32'},count:1,total_count:1,downsampled:false,truncated:false,from_timestamp:'',to_timestamp:'',
      points:[{recorded_at:'2026-09-01T00:00:00Z',source_timestamp:null,value_numeric:12,value_numeric_exact:'12',value_boolean:null,value_text:null,quality:id===1?'GOOD':'COMM_ERROR',minimum:null,maximum:null,average:null,first_timestamp:'2026-09-01T00:00:00Z',last_timestamp:'2026-09-01T00:00:00Z',sample_count:1,has_invalid:id===2}],
    }));
    render(<ChartWidget widget={{...widget,type:'chart',tag_ids:[1,2],configuration:{legend:true}}} />);
    await screen.findByRole('img',{name:'Historical line chart'});
    expect(chart.setOption).toHaveBeenCalledWith(expect.objectContaining({series:[
      expect.objectContaining({name:'Tag 1',connectNulls:false,data:[['2026-09-01T00:00:00Z',12]]}),
      expect.objectContaining({name:'Tag 2',connectNulls:false,data:[['2026-09-01T00:00:00Z',null]]}),
    ]}));
    expect(chart.setOption).toHaveBeenCalledWith(expect.objectContaining({ tooltip: expect.objectContaining({ confine: true }), xAxis: expect.objectContaining({ splitNumber: 3 }), legend: expect.objectContaining({ type: 'scroll' }) }));
  });
  it('loads history independently, handles empty/error and changes range', async () => {
    const get = vi.spyOn(historyApi,'getHistory').mockResolvedValue({tag:{id:1,key:'reading',name:'Reading',unit:'C',data_type:'float32'},count:0,total_count:0,downsampled:false,truncated:false,from_timestamp:'',to_timestamp:'',points:[]});
    render(<ChartWidget widget={{...widget,type:'chart'}} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading history'); expect(await screen.findByText('No history in this range')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('combobox',{name:'Chart range'})); await userEvent.click(screen.getByRole('option',{name:'6 hours'}));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    const [,from,to] = get.mock.calls[1]; expect(new Date(to).getTime()-new Date(from).getTime()).toBe(6*3600000);
    get.mockRejectedValue(new Error('History offline')); await userEvent.click(screen.getByRole('button',{name:'Refresh history'}));
    expect(await screen.findByText('History offline')).toBeInTheDocument();
  });
});

describe('dashboard connectivity', () => {
  const edgeAuth = { ...testAuth, user: { ...testAuth.user!, application_mode: 'edge' } };
  it('does not request synchronization for standalone', () => {
    const get = vi.spyOn(client, 'request');
    render(<DashboardConnectivity />);
    expect(get).not.toHaveBeenCalled();
  });
  it.each([true, false])('uses existing Edge sync time to show connected=%s', async connected => {
    vi.spyOn(client, 'request').mockResolvedValue({ mode: 'edge', last_sync_at: new Date(Date.now() - (connected ? 5000 : 60000)).toISOString(), error: null, edges: [] } as never);
    render(<AuthContext.Provider value={edgeAuth}><DashboardConnectivity /></AuthContext.Provider>);
    expect(await screen.findByText(connected ? 'CONNECTED' : 'DISCONNECTED')).toBeInTheDocument();
  });
  it('shows unavailable status on API failure instead of reporting healthy', async () => {
    vi.spyOn(client, 'request').mockRejectedValue(new Error('Fixture failure'));
    render(<AuthContext.Provider value={edgeAuth}><DashboardConnectivity /></AuthContext.Provider>);
    expect(await screen.findByText('Connectivity: unavailable')).toBeInTheDocument();
  });
  it('shows Edge states on Cloud without machine identifiers', async () => {
    vi.spyOn(client, 'request').mockResolvedValue({ mode: 'cloud', edges: [{ name: 'Site A', enabled: true, state: 'ONLINE' }, { name: 'Site B', enabled: true, state: 'OFFLINE' }] } as never);
    render(<AuthContext.Provider value={{ ...edgeAuth, user: { ...edgeAuth.user, application_mode: 'cloud' } }}><DashboardConnectivity /></AuthContext.Provider>);
    expect(await screen.findByText('Edge: 1 / 2 ONLINE')).toBeInTheDocument();
    expect(screen.getByText('Site B: OFFLINE')).toBeInTheDocument();
  });
});
