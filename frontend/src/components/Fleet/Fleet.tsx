import { useEffect, useState } from 'react';
import './fleet.css';

type BatteryType = 'unknown' | 'alkaline' | 'li-poly' | 'li-ion';
type Config = {
  configured: boolean; display: string; panel_profile: string;
  name: string; lat: number | null; long: number | null;
  battery_type: BatteryType; battery_cells: number;
};
type Panel = {
  id: string; friendly_name: string; registered_at: number; last_seen: number;
  config: Config; config_version: string; reported_version: string | null;
  width: number; height: number; battery_voltage: number | null;
  battery_reported_at: number | null; battery_percent: number | null;
  power_source: 'usb' | 'battery' | null;
  image: { state: string; rendered_at?: number | null; error?: string | null };
};

const date = (value: number | null | undefined) => value ? new Date(value * 1000).toLocaleString() : 'Not reported';

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/admin/api${path}`, { credentials: 'same-origin', ...options });
  if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Your login has expired. Reload this page to sign in.');
  }
  const body = await response.json();
  if (!response.ok) {
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Unable to save these settings. Check the form values.');
  }
  return body;
}

export default function Fleet() {
  const [panels, setPanels] = useState<Panel[]>([]);
  const [selected, setSelected] = useState<Panel | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const items = await api<Panel[]>('/panels');
        if (active) { setPanels(items); setError(''); }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'Unable to load panels.');
      } finally {
        if (active) setLoading(false);
      }
    };
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const saved = (panel: Panel) => {
    setPanels(items => items.map(item => item.id === panel.id ? panel : item));
    setSelected(null);
    setNotice('Settings saved. The panel will receive them at its next check-in.');
  };

  return <main className="fleet">
    <header className="fleet-header">
      <div><a href="/">Weather dashboard</a><h1>Panel fleet</h1><p>Configure displays and monitor their last check-in.</p></div>
      <span className="fleet-count">{panels.length} {panels.length === 1 ? 'panel' : 'panels'}</span>
    </header>
    {error && <p role="alert" className="fleet-error">{error} <a href="/admin">Reload</a></p>}
    {notice && <p role="status" className="fleet-notice">{notice}</p>}
    {loading ? <p>Loading panels…</p> : !panels.length ? <section className="fleet-empty"><h2>Waiting for your first panel</h2><p>Set the dashboard URL on a panel and run Weather. It will register here automatically.</p></section> :
      <div className="fleet-table-wrap"><table>
        <thead><tr><th>Panel</th><th>Location</th><th>Last contact</th><th>Battery / power</th><th>Configuration</th><th>Weather image</th><th><span className="fleet-sr-only">Actions</span></th></tr></thead>
        <tbody>{panels.map(panel => <tr key={panel.id}>
          <td><strong>{panel.friendly_name || 'Unnamed panel'}</strong><code>{panel.id}</code><small>{panel.width} × {panel.height}</small></td>
          <td>{panel.config.configured ? panel.config.name || `${panel.config.lat}, ${panel.config.long}` : <span className="fleet-badge">Needs setup</span>}</td>
          <td>{date(panel.last_seen)}</td>
          <td>{panel.power_source === 'usb' && <strong>USB powered<br /></strong>}
            {panel.battery_voltage !== null ? <>{panel.battery_percent !== null ? `≈ ${panel.battery_percent}% · ` : ''}{panel.battery_voltage.toFixed(2)} V<small>Battery measured {date(panel.battery_reported_at)}</small></> : 'Battery not reported'}</td>
          <td>{panel.reported_version === panel.config_version ? 'Synced' : 'Awaiting check-in'}</td>
          <td><span className={`fleet-badge ${panel.image.state === 'failed' ? 'fleet-failed' : ''}`}>{panel.image.state}</span><small>{panel.image.rendered_at ? date(panel.image.rendered_at) : ''}</small>{panel.image.error && <small className="fleet-error">{panel.image.error}</small>}</td>
          <td><button onClick={() => { setSelected(panel); setNotice(''); }}>Configure</button></td>
        </tr>)}</tbody>
      </table></div>}
    {selected && <Editor key={selected.id} panel={selected} onSave={saved} onCancel={() => setSelected(null)} />}
    <p className="fleet-footnote">Battery percentages are approximate voltage estimates. Weather is prepared five minutes before the scheduled refresh.</p>
  </main>;
}

function Editor({ panel, onSave, onCancel }: { panel: Panel; onSave: (panel: Panel) => void; onCancel: () => void }) {
  const [friendlyName, setFriendlyName] = useState(panel.friendly_name);
  const [config, setConfig] = useState(panel.config);
  const [lat, setLat] = useState(panel.config.lat?.toString() ?? '');
  const [long, setLong] = useState(panel.config.long?.toString() ?? '');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true); setError('');
    try {
      const { configured: _configured, ...settings } = config;
      void _configured;
      onSave(await api<Panel>(`/panels/${panel.id}/config`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...settings, friendly_name: friendlyName, lat: Number(lat), long: Number(long) }),
      }));
    } catch (err) { setError(err instanceof Error ? err.message : 'Save failed.'); }
    finally { setSaving(false); }
  };
  return <section className="fleet-editor" aria-labelledby="edit-panel">
    <h2 id="edit-panel">Configure {panel.friendly_name || panel.id}</h2>
    <form onSubmit={submit}>
      <label>Panel name<input maxLength={120} value={friendlyName} onChange={e => setFriendlyName(e.target.value)} /></label>
      <label>Location name<input maxLength={160} value={config.name} onChange={e => setConfig({ ...config, name: e.target.value })} /></label>
      <label>Latitude<input type="number" step="any" min={-90} max={90} required value={lat} onChange={e => setLat(e.target.value)} /></label>
      <label>Longitude<input type="number" step="any" min={-180} max={180} required value={long} onChange={e => setLong(e.target.value)} /></label>
      <label>Hardware<select value={config.display} onChange={e => setConfig({ ...config, display: e.target.value })}><option value="inky-frame-spectra-7">Inky Frame 7.3-inch Spectra 6</option></select></label>
      <label>Palette<select value={config.panel_profile} onChange={e => setConfig({ ...config, panel_profile: e.target.value })}><option value="spectra6">Spectra 6</option><option value="spectra6-boeber">Spectra 6 Böber calibration</option><option value="generic-2-color-eink">Black and white</option><option value="none">Full color</option></select></label>
      <label>Battery chemistry<select value={config.battery_type} onChange={e => {
        const battery_type = e.target.value as BatteryType;
        setConfig({ ...config, battery_type, battery_cells: battery_type === 'li-poly' || battery_type === 'li-ion' ? 1 : 3 });
      }}><option value="unknown">Unknown — report voltage only</option><option value="alkaline">Alkaline</option><option value="li-poly">Lithium polymer</option><option value="li-ion">Lithium ion</option></select></label>
      <label>Cells in series<input type="number" min={1} max={config.battery_type === 'li-poly' || config.battery_type === 'li-ion' ? 1 : 4} required value={config.battery_cells} onChange={e => setConfig({ ...config, battery_cells: Number(e.target.value) })} /></label>
      {error && <p role="alert" className="fleet-error">{error}</p>}
      <div className="fleet-actions"><button disabled={saving} type="submit">{saving ? 'Saving…' : 'Save settings'}</button><button disabled={saving} type="button" className="fleet-secondary" onClick={onCancel}>Cancel</button></div>
    </form>
  </section>;
}
