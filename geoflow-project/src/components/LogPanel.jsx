import { useEffect, useRef, useState } from 'react';
import Icon from './Icon.jsx';
import { useLogs } from '../workflow/WorkflowContext.jsx';

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export default function LogPanel() {
  const { logs, clearLogs } = useLogs();
  const [open, setOpen] = useState(false);
  const listRef = useRef(null);
  const last = logs[logs.length - 1];
  const errors = logs.filter((l) => l.level === 'error').length;

  useEffect(() => {
    if (open && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [logs, open]);

  return (
    <div className={`gf-console ${open ? 'is-open' : ''}`}>
      <button type="button" className="gf-console__bar" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Icon name="terminal" size={13} />
        <span className="gf-console__title">Console</span>
        {errors > 0 && <span className="gf-badge gf-badge--error">{errors}</span>}
        {!open && last && <span className={`gf-console__last gf-log--${last.level}`}>{last.message}</span>}
        <Icon name="chevron" size={14} className="gf-console__chevron" />
      </button>
      {open && (
        <div className="gf-console__body">
          <div ref={listRef} className="gf-console__list">
            {logs.length === 0 && <div className="gf-console__empty">Run a node to see activity here.</div>}
            {logs.map((l) => (
              <div key={l.id} className={`gf-log gf-log--${l.level}`}>
                <span className="gf-log__time gf-mono">{timeFormat.format(l.time)}</span>
                <span className="gf-log__msg">{l.message}</span>
              </div>
            ))}
          </div>
          {logs.length > 0 && (
            <button type="button" className="gf-btn gf-btn--ghost gf-btn--small gf-console__clear" onClick={clearLogs}>
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}
