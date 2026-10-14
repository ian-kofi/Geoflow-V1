/**
 * Runs workflows: works out the order nodes need to run in, sends each one to the backend and
 * stores what comes back on the node.
 */
import { useCallback, useRef, useState } from 'react';
import { useReactFlow } from '@xyflow/react';
import { API_URL, MAX_PARALLEL } from '../config.js';
import { NODE_TYPES } from '../nodes/registry.js';
import { fileStore } from './fileStore.js';
import { parentsOf, stableStringify, topoSort, withAncestors } from './graph.js';

/** Thrown for a node that wasn't run because a node before it failed. */
class SkipError extends Error {}

/**
 * Makes a queue that runs at most `max` tasks at the same time. Each task is a function
 * returning a promise; the rest wait their turn.
 */
function createLimiter(max) {
  let active = 0;
  const waiting = [];
  const next = () => {
    if (active >= max || !waiting.length) return;
    active += 1;
    const { task, resolve, reject } = waiting.shift();
    task()
      .then(resolve, reject)
      .finally(() => {
        active -= 1;
        next();
      });
  };
  return (task) =>
    new Promise((resolve, reject) => {
      waiting.push({ task, resolve, reject });
      next();
    });
}

/** Just the node's settings, leaving out everything else stored on it (status, result and so on). */
function paramValues(type, data) {
  const def = NODE_TYPES[type];
  return Object.fromEntries(def.params.map((p) => [p.key, data[p.key]]));
}

/**
 * Sends one node to the backend's /upload endpoint and returns its result.
 *
 * The form holds the node's type and id, the results of the nodes connected to it, any place
 * typed into a connected Place node, its settings and any files chosen for it.
 */
async function callBackend(node, parentNodes, parentOutputs, signal) {
  const def = NODE_TYPES[node.type];
  const form = new FormData();
  form.append('nodeType', node.type);
  form.append('nodeId', node.id);
  form.append('parentOutputs', JSON.stringify(parentOutputs));

  const locations = Object.fromEntries(
    parentNodes.filter((p) => p.type === 'LocationNode' && p.data.location).map((p) => [p.id, p.data.location.trim()]),
  );
  if (Object.keys(locations).length) form.append('locations', JSON.stringify(locations));

  for (const param of def.params) {
    if (param.type === 'folder') {
      for (const file of fileStore.get(node.id)) {
        const rel = file.webkitRelativePath || file.name;
        form.append(`geo_${rel}`, file, rel);
      }
    } else if (param.type === 'file') {
      // The backend keeps a copy for each node, so after a page reload (when the browser no
      // longer has the file) it uses that copy instead.
      for (const file of fileStore.get(node.id)) form.append('upload', file, file.name);
    } else if (node.data[param.key] !== undefined && node.data[param.key] !== null) {
      form.append(param.key, String(node.data[param.key]));
    }
  }

  let response;
  try {
    response = await fetch(`${API_URL}/upload`, { method: 'POST', body: form, signal });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new Error(`Cannot reach the backend at ${API_URL}. Is uvicorn running?`);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.status === 'error') {
    throw new Error(body.detail || `Backend error (HTTP ${response.status})`);
  }
  return body;
}

/**
 * The workflow runner. Returns `execute` to run nodes, `stop` to cancel a run, whether a run is
 * going on, and the messages shown in the Console panel.
 */
export function useWorkflowRunner() {
  const { getNodes, getEdges, updateNodeData } = useReactFlow();
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const abortRef = useRef(null);

  // Adds a message to the Console, keeping the last 200
  const log = useCallback((level, message) => {
    setLogs((prev) => [...prev.slice(-199), { id: `${Date.now()}_${Math.random()}`, time: new Date(), level, message }]);
  }, []);

  const clearLogs = useCallback(() => setLogs([]), []);

  /**
   * Runs the given nodes, plus every node they depend on. Pass null to run the whole canvas.
   *
   * Each node starts as soon as the nodes before it have finished, so separate branches run at
   * the same time (up to MAX_PARALLEL at once). A node whose settings and inputs haven't changed
   * since its last successful run isn't sent again; its saved result is reused. Set `force` to
   * run everything regardless.
   */
  const execute = useCallback(
    async (targetIds, { force = false } = {}) => {
      if (abortRef.current) return;
      const nodes = getNodes();
      const edges = getEdges();
      const byId = new Map(nodes.map((n) => [n.id, n]));
      const ids = targetIds ? [...withAncestors(targetIds, edges)] : nodes.map((n) => n.id);
      if (!ids.length) return;

      let order;
      try {
        order = topoSort(ids, edges);
      } catch (err) {
        log('error', err.message);
        return;
      }

      const controller = new AbortController();
      abortRef.current = controller;
      setRunning(true);
      const started = performance.now();
      const results = new Map();
      const tasks = new Map();
      const limit = createLimiter(MAX_PARALLEL);
      let executed = 0;
      let cached = 0;
      let failed = 0;

      order.forEach((id) => updateNodeData(id, { status: 'queued' }));
      log('info', `Running ${order.length} node${order.length === 1 ? '' : 's'}${force ? ' (forced)' : ''}…`);

      // Runs one node after its parents. Each node gets one task, so a node feeding several
      // others is still only run once.
      const runNode = (id) => {
        if (tasks.has(id)) return tasks.get(id);
        const task = (async () => {
          const node = byId.get(id);
          const def = NODE_TYPES[node.type];
          const parentIds = parentsOf(id, edges);
          const parentStates = await Promise.allSettled(parentIds.map(runNode));
          if (parentStates.some((s) => s.status === 'rejected')) {
            if (controller.signal.aborted) updateNodeData(id, { status: node.data.result ? 'stale' : 'idle' });
            else updateNodeData(id, { status: 'skipped', error: 'An upstream node failed.' });
            throw new SkipError();
          }

          const parentNodes = [...new Set(parentIds)].map((p) => byId.get(p));
          // One entry per connection, marked with the input it's plugged into (like Spatial
          // Filter's "data" and "mask"), so the backend can tell them apart.
          const parentOutputs = edges
            .filter((e) => e.target === id && results.has(e.source))
            .map((e) => (e.targetHandle ? { ...results.get(e.source), _input: e.targetHandle } : results.get(e.source)));
          // A fingerprint of everything that decides this node's result. If it matches the
          // last run, the saved result can be reused.
          const signature = stableStringify({
            type: node.type,
            params: paramValues(node.type, node.data), // file settings hold a fingerprint of the chosen files
            place: node.data.place?.id, // a different place with the same name must run again
            parentOutputs,
          });

          if (!force && node.data.result && node.data.signature === signature) {
            results.set(id, node.data.result);
            updateNodeData(id, { status: 'done', error: null });
            cached += 1;
            return node.data.result;
          }

          return limit(async () => {
            if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
            updateNodeData(id, { status: 'running', error: null, startedAt: Date.now() });
            const t0 = performance.now();
            try {
              let result;
              // The Place node needs no server work: its result is just the place itself
              if (def.clientOnly) {
                const location = node.data.location?.trim();
                if (!location) throw new Error('Enter a place name.');
                const place = node.data.place ?? null;
                if (!place) log('warn', `“${location}” wasn't picked from the list, so the first place with that name will be used.`);
                result = { status: 'ok', location, place };
              } else {
                result = await callBackend(node, parentNodes, parentOutputs, controller.signal);
              }
              const elapsed = (performance.now() - t0) / 1000;
              results.set(id, result);
              updateNodeData(id, { status: 'done', result, signature, elapsed, error: null });
              executed += 1;
              if (!def.clientOnly) log('success', `${def.label} (${id}) finished in ${elapsed.toFixed(1)}s`);
              return result;
            } catch (err) {
              if (err.name === 'AbortError') {
                updateNodeData(id, { status: node.data.result ? 'stale' : 'idle', error: null });
              } else {
                failed += 1;
                updateNodeData(id, { status: 'error', error: err.message });
                log('error', `${def.label} (${id}): ${err.message}`);
              }
              throw err;
            }
          });
        })();
        tasks.set(id, task);
        return task;
      };

      await Promise.allSettled(order.map(runNode));

      // Any node still marked as queued was never reached (because Stop was pressed, for example).
      getNodes()
        .filter((n) => n.data.status === 'queued')
        .forEach((n) => updateNodeData(n.id, { status: n.data.result ? 'stale' : 'idle' }));

      const total = ((performance.now() - started) / 1000).toFixed(1);
      if (controller.signal.aborted) log('warn', 'Run stopped.');
      else
        log(
          failed ? 'warn' : 'success',
          `Done in ${total}s · ${executed} ran · ${cached} cached${failed ? ` · ${failed} failed` : ''}`,
        );
      abortRef.current = null;
      setRunning(false);
    },
    [getNodes, getEdges, updateNodeData, log],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return { execute, stop, running, logs, log, clearLogs };
}
