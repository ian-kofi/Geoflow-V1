import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import GeoNode from './nodes/GeoNode.jsx';
import { createNode, NODE_TYPES } from './nodes/registry.js';
import Sidebar, { DRAG_MIME } from './components/Sidebar.jsx';
import Toolbar from './components/Toolbar.jsx';
import Inspector, { collectMapLayers, MapPreview } from './components/Inspector.jsx';
import LogPanel from './components/LogPanel.jsx';
import { WorkflowProvider, useWorkflow } from './workflow/WorkflowContext.jsx';
import { createsCycle } from './workflow/graph.js';
import { fileStore } from './workflow/fileStore.js';
import { TEMPLATES } from './workflow/templates.js';
import { SIDEBAR_KEY, STORAGE_KEY } from './config.js';
import { downloadJson } from './utils.js';
import { useTheme } from './useTheme.js';
import { UiContext } from './uiContext.js';
import QuickMapDialog from './components/QuickMapDialog.jsx';
import Icon from './components/Icon.jsx';

const nodeTypes = Object.fromEntries(Object.keys(NODE_TYPES).map((type) => [type, GeoNode]));
const TRANSIENT_STATUS = new Set(['queued', 'running']);

/** Brings saved/imported nodes into a consistent state (files and in-flight runs don't survive a reload). */
function sanitize({ nodes = [], edges = [] }) {
  const valid = nodes.filter((n) => NODE_TYPES[n.type]);
  const ids = new Set(valid.map((n) => n.id));
  return {
    nodes: valid.map(({ id, type, position, data, width, height }) => {
      const { geoFiles, startedAt, ...rest } = data ?? {};
      const status = TRANSIENT_STATUS.has(rest.status) ? (rest.result ? 'stale' : 'idle') : rest.status ?? 'idle';
      const { resizable } = NODE_TYPES[type];
      // Resizable nodes keep their size; older saves get the default size.
      const size = resizable
        ? { width: width ?? resizable.width, ...(rest.collapsed ? {} : { height: height ?? resizable.height }) }
        : {};
      return { id, type, position, ...size, data: { ...NODE_TYPES[type].defaults, ...rest, status } };
    }),
    edges: edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map(({ id, source, target, targetHandle }) => ({
        id: id ?? `e_${source}_${target}`,
        source,
        target,
        ...(targetHandle ? { targetHandle } : {}),
      })),
  };
}

function loadInitial() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved?.nodes) return { ...sanitize(saved), firstVisit: false };
  } catch {
    /* fall through to an empty canvas */
  }
  // First visit: start empty and open the "Make a map" assistant.
  return { nodes: [], edges: [], firstVisit: true };
}

/** Where to put newly added nodes: to the right of whatever is already on the canvas. */
function placeBeside(existing, added) {
  if (!existing.length) return added;
  const right = Math.max(...existing.map((n) => n.position.x + (n.measured?.width ?? n.width ?? 280)));
  const top = Math.min(...existing.map((n) => n.position.y));
  return added.map((n) => ({ ...n, position: { x: n.position.x + right + 160, y: n.position.y + top } }));
}

function Editor() {
  const [initial] = useState(loadInitial);
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const { screenToFlowPosition, fitView, getEdges, getNodes } = useReactFlow();
  const { runAll, runNode, stop, running, markStale, log } = useWorkflow();
  const [quickMapOpen, setQuickMapOpen] = useState(initial.firstVisit);
  const [pendingRun, setPendingRun] = useState(null);

  // Run a freshly built map once its nodes are in the flow store.
  useEffect(() => {
    if (!pendingRun || running || !getNodes().some((n) => n.id === pendingRun.outputId)) return;
    const { outputId, nodeIds } = pendingRun;
    setPendingRun(null);
    fitView({ nodes: nodeIds.map((id) => ({ id })), padding: 0.15, duration: 600 });
    runNode(outputId);
  }, [pendingRun, nodes, running, getNodes, fitView, runNode]);

  const createQuickMap = useCallback(
    (recipe, place) => {
      const built = recipe.build(place);
      const added = placeBeside(getNodes(), built.nodes).map((n) => ({ ...n, selected: n.id === built.outputId }));
      setNodes((ns) => [...ns.map((n) => (n.selected ? { ...n, selected: false } : n)), ...added]);
      setEdges((es) => [...es, ...built.edges]);
      setQuickMapOpen(false);
      setInspectorOpen(true);
      setTab('node');
      setPendingRun({ outputId: built.outputId, nodeIds: added.map((n) => n.id) });
      log('info', `Making “${recipe.title}” for ${place.name}… (${recipe.time})`);
    },
    [getNodes, setNodes, setEdges, log],
  );
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [tab, setTab] = useState('node');
  const [mapFocus, setMapFocus] = useState(null);
  const [mapExpanded, setMapExpanded] = useState(false);
  const toggleMapExpanded = useCallback(() => setMapExpanded((e) => !e), []);
  const ui = useMemo(
    () => ({
      showOnMap: (bounds) => {
        setInspectorOpen(true);
        setTab('map');
        setMapFocus({ bounds, requestedAt: Date.now() });
      },
    }),
    [],
  );
  const { theme, toggleTheme } = useTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === 'collapsed';
    } catch {
      return false;
    }
  });
  const canvasRef = useRef(null);

  // Autosave (debounced so dragging doesn't serialize on every frame)
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitize({ nodes, edges })));
      } catch {
        /* storage full or unavailable — autosave is best-effort */
      }
    }, 500);
    return () => clearTimeout(t);
  }, [nodes, edges]);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, sidebarCollapsed ? 'collapsed' : 'expanded');
    } catch {
      /* storage unavailable — the choice just won't persist */
    }
  }, [sidebarCollapsed]);

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!running) runAll({ force: e.shiftKey });
      } else if (e.key === 'Escape' && running) {
        stop();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [runAll, stop, running]);

  const expandedLayers = useMemo(() => (mapExpanded ? collectMapLayers(nodes) : []), [mapExpanded, nodes]);

  const counts = useMemo(() => {
    const c = { total: nodes.length, done: 0, error: 0, collapsed: 0 };
    nodes.forEach((n) => {
      if (n.data.status === 'done') c.done += 1;
      if (n.data.status === 'error') c.error += 1;
      if (n.data.collapsed) c.collapsed += 1;
    });
    return c;
  }, [nodes]);

  // Edge animation depends only on node status; avoid rebuilding edges while dragging.
  const edgeStateKey = nodes.map((n) => `${n.id}:${n.data.status}`).join('|');
  const displayEdges = useMemo(() => {
    const status = new Map(nodes.map((n) => [n.id, n.data.status]));
    return edges.map((e) => ({ ...e, animated: status.get(e.target) === 'running' }));
  }, [edges, edgeStateKey]);

  const selectedNode = nodes.find((n) => n.selected);

  const isValidConnection = useCallback(
    (conn) => {
      const current = getEdges();
      const handle = conn.targetHandle ?? null;
      const incoming = current.filter((e) => e.target === conn.target);
      // A named input (e.g. "Mask") takes one connection; the default input takes many.
      if (handle && incoming.some((e) => e.targetHandle === handle)) return false;
      if (incoming.some((e) => e.source === conn.source && (e.targetHandle ?? null) === handle)) return false;
      return !createsCycle(conn.source, conn.target, current);
    },
    [getEdges],
  );

  const onConnect = useCallback(
    (conn) => {
      setEdges((eds) => addEdge({ ...conn, id: `e_${conn.source}_${conn.target}${conn.targetHandle ? `_${conn.targetHandle}` : ''}` }, eds));
      markStale(conn.target);
    },
    [setEdges, markStale],
  );

  const onEdgesDelete = useCallback((deleted) => deleted.forEach((e) => markStale(e.target)), [markStale]);
  const onNodesDelete = useCallback((deleted) => deleted.forEach((n) => fileStore.delete(n.id)), []);

  const addNode = useCallback(
    (type, position) => {
      let pos = position;
      if (!pos) {
        const rect = canvasRef.current?.getBoundingClientRect();
        const center = screenToFlowPosition({
          x: rect ? rect.left + rect.width / 2 : window.innerWidth / 2,
          y: rect ? rect.top + rect.height / 2 : window.innerHeight / 2,
        });
        pos = { x: center.x - 130 + (Math.random() - 0.5) * 60, y: center.y - 60 + (Math.random() - 0.5) * 60 };
      }
      const node = { ...createNode(type, pos), selected: true };
      setNodes((ns) => [...ns.map((n) => (n.selected ? { ...n, selected: false } : n)), node]);
    },
    [screenToFlowPosition, setNodes],
  );

  const onDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      const type = e.dataTransfer.getData(DRAG_MIME);
      if (!NODE_TYPES[type]) return;
      const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      addNode(type, { x: pos.x - 130, y: pos.y - 24 });
    },
    [screenToFlowPosition, addNode],
  );

  const replaceWorkflow = useCallback(
    (workflow) => {
      nodes.forEach((n) => fileStore.delete(n.id));
      setNodes(workflow.nodes);
      setEdges(workflow.edges);
      requestAnimationFrame(() => fitView({ padding: 0.2, duration: 400 }));
    },
    [nodes, setNodes, setEdges, fitView],
  );

  const onTemplate = useCallback(
    (template) => {
      if (nodes.length && !window.confirm(`Replace the current workflow with “${template.name}”?`)) return;
      replaceWorkflow(template.build());
      log('info', `Loaded template “${template.name}”. Press Run workflow to execute it.`);
    },
    [nodes.length, replaceWorkflow, log],
  );

  const onExport = useCallback(() => {
    downloadJson({ app: 'GeoFlow', version: 1, ...sanitize({ nodes, edges }) }, 'geoflow-workflow.json');
  }, [nodes, edges]);

  const onImport = useCallback(
    async (file) => {
      try {
        const workflow = sanitize(JSON.parse(await file.text()));
        if (!workflow.nodes.length) throw new Error('No nodes found');
        replaceWorkflow(workflow);
        log('info', `Imported ${workflow.nodes.length} nodes from ${file.name}`);
      } catch (err) {
        log('error', `Import failed: ${err.message}`);
      }
    },
    [replaceWorkflow, log],
  );

  const onClear = useCallback(() => {
    if (nodes.length && window.confirm('Remove all nodes from the canvas?')) replaceWorkflow({ nodes: [], edges: [] });
  }, [nodes.length, replaceWorkflow]);

  return (
    <UiContext.Provider value={ui}>
    <div
      className={`gf-app ${inspectorOpen ? '' : 'is-inspector-closed'} ${sidebarCollapsed ? 'is-sidebar-collapsed' : ''}`}
    >
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((c) => !c)}
        onMakeMap={() => setQuickMapOpen(true)}
        onAdd={addNode} onTemplate={onTemplate} onExport={onExport} onImport={onImport} onClear={onClear} />

      <main className="gf-canvas" ref={canvasRef}>
        <div className="gf-canvas__flow">
          <ReactFlow
            nodes={nodes}
            edges={displayEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onEdgesDelete={onEdgesDelete}
            onNodesDelete={onNodesDelete}
            isValidConnection={isValidConnection}
            onDrop={onDrop}
            onDragOver={onDragOver}
            colorMode={theme}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.15}
            maxZoom={2}
            snapToGrid
            snapGrid={[10, 10]}
            deleteKeyCode={['Backspace', 'Delete']}
            attributionPosition="bottom-left"
          >
            <Background />
            {!mapExpanded && <Controls position="bottom-left" showInteractive={false} style={{ marginBottom: 32 }} />}
            {!mapExpanded && <MiniMap position="bottom-right" pannable zoomable />}
            {mapExpanded && (
              // Covers the node canvas (which stays mounted underneath); the toolbar panel sits above it.
              <div className="gf-canvas__map nodrag nopan nowheel">
                <Suspense fallback={<div className="gf-map gf-map--loading">Loading map…</div>}>
                  <MapPreview layers={expandedLayers} theme={theme} focus={mapFocus} expanded onToggleExpand={toggleMapExpanded} />
                </Suspense>
              </div>
            )}
            <Panel position="top-center">
              <Toolbar
                counts={counts}
                inspectorOpen={inspectorOpen}
                onToggleInspector={() => setInspectorOpen((o) => !o)}
                theme={theme}
                onToggleTheme={toggleTheme}
              />
            </Panel>
            {nodes.length === 0 && !mapExpanded && (
              <Panel position="top-center" className="gf-empty-canvas">
                <h2>What would you like to map?</h2>
                <p>Pick a place and what to see, and GeoFlow builds the map for you.</p>
                <button type="button" className="gf-btn gf-btn--primary gf-empty-canvas__main" onClick={() => setQuickMapOpen(true)}>
                  <Icon name="map" size={15} /> Make a map
                </button>
                <p className="gf-hint">Or start from an example, or drag building blocks from the left:</p>
                <div className="gf-empty-canvas__actions">
                  {TEMPLATES.map((t) => (
                    <button key={t.id} type="button" className="gf-btn gf-btn--ghost" onClick={() => onTemplate(t)}>
                      {t.name}
                    </button>
                  ))}
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>
        <LogPanel />
      </main>

      {inspectorOpen && (
        <Inspector
          tab={tab}
          onTabChange={setTab}
          selectedNode={selectedNode}
          nodes={nodes}
          counts={counts}
          theme={theme}
          mapFocus={mapFocus}
          mapExpanded={mapExpanded}
          onToggleMapExpanded={toggleMapExpanded}
          onClose={() => setInspectorOpen(false)}
        />
      )}
      {quickMapOpen && <QuickMapDialog onClose={() => setQuickMapOpen(false)} onCreate={createQuickMap} />}
    </div>
    </UiContext.Provider>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <WorkflowProvider>
        <Editor />
      </WorkflowProvider>
    </ReactFlowProvider>
  );
}
