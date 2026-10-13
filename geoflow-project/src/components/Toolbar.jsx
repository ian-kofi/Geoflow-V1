import { useEffect, useState } from 'react';
import { useReactFlow } from '@xyflow/react';
import Icon from './Icon.jsx';
import { API_URL } from '../config.js';
import { useWorkflow } from '../workflow/WorkflowContext.jsx';

function useBackendStatus() {
  const [status, setStatus] = useState('checking');
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch(`${API_URL}/health`, { cache: 'no-store' });
        if (!cancelled) setStatus(res.ok ? 'online' : 'offline');
      } catch {
        if (!cancelled) setStatus('offline');
      }
    };
    check();
    const t = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);
  return status;
}

export default function Toolbar({ counts, inspectorOpen, onToggleInspector, theme, onToggleTheme }) {
  const { runAll, stop, running } = useWorkflow();
  const backend = useBackendStatus();
  const { setNodes } = useReactFlow();
  const allCollapsed = counts.total > 0 && counts.collapsed === counts.total;
  const setAllCollapsed = (collapsed) =>
    setNodes((nodes) => nodes.map((n) => (Boolean(n.data.collapsed) === collapsed ? n : { ...n, data: { ...n.data, collapsed } })));
  const progress = counts.total ? (counts.done / counts.total) * 100 : 0;

  return (
    <div className="gf-toolbar">
      {running ? (
        <button type="button" className="gf-btn gf-btn--danger" onClick={stop} title="Stop (Esc)">
          <Icon name="stop" size={12} /> Stop
        </button>
      ) : (
        <button
          type="button"
          className="gf-btn gf-btn--primary"
          onClick={(e) => runAll({ force: e.shiftKey })}
          disabled={!counts.total}
          title="Run changed nodes (Ctrl+Enter). Shift+click re-runs everything."
        >
          <Icon name="play" size={12} /> Run workflow
        </button>
      )}
      <button
        type="button"
        className="gf-icon-btn"
        onClick={() => runAll({ force: true })}
        disabled={running || !counts.total}
        title="Re-run every node, ignoring cached results"
      >
        <Icon name="refresh" size={15} />
      </button>

      <div className="gf-toolbar__divider" />

      <div className="gf-progress" title={`${counts.done} of ${counts.total} nodes up to date`}>
        <div className="gf-progress__label">
          <span className="gf-mono">
            {counts.done}/{counts.total}
          </span>{' '}
          up to date
          {counts.error > 0 && <span className="gf-progress__err"> · {counts.error} failed</span>}
        </div>
        <div className="gf-progress__track">
          <div className={`gf-progress__bar ${running ? 'is-running' : ''}`} style={{ width: `${progress}%` }} />
        </div>
      </div>

      <div className="gf-toolbar__divider" />

      <button
        type="button"
        className="gf-icon-btn"
        onClick={() => setAllCollapsed(!allCollapsed)}
        disabled={!counts.total}
        title={allCollapsed ? 'Expand all nodes' : 'Collapse all nodes'}
        aria-label={allCollapsed ? 'Expand all nodes' : 'Collapse all nodes'}
      >
        <Icon name={allCollapsed ? 'expandAll' : 'collapseAll'} size={15} />
      </button>

      <span className={`gf-backend gf-backend--${backend}`} title={`Backend: ${API_URL}`}>
        <span className="gf-status__dot" />
        {backend === 'online' ? 'Backend online' : backend === 'offline' ? 'Backend offline' : 'Checking…'}
      </span>

      <button
        type="button"
        className="gf-icon-btn"
        onClick={onToggleTheme}
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={15} />
      </button>
      <button
        type="button"
        className={`gf-icon-btn ${inspectorOpen ? 'is-active' : ''}`}
        onClick={onToggleInspector}
        title="Toggle inspector"
      >
        <Icon name="panel" size={15} />
      </button>
    </div>
  );
}
