import { createContext, useCallback, useContext, useMemo } from 'react';
import { useReactFlow } from '@xyflow/react';
import { useWorkflowRunner } from './useWorkflowRunner.js';
import { descendantsOf } from './graph.js';
import { fileStore } from './fileStore.js';

// Split in two so log updates don't re-render every node on the canvas.
const ActionsContext = createContext(null);
const LogsContext = createContext(null);

export function WorkflowProvider({ children }) {
  const { getNodes, getEdges, updateNodeData, deleteElements } = useReactFlow();
  const { execute, stop, running, logs, log, clearLogs } = useWorkflowRunner();

  /** Marks finished nodes as stale (outputs no longer match their inputs). */
  const markStale = useCallback(
    (id, includeSelf = true) => {
      const nodes = new Map(getNodes().map((n) => [n.id, n]));
      const ids = [...descendantsOf(id, getEdges())];
      if (includeSelf) ids.push(id);
      ids.forEach((nid) => {
        if (nodes.get(nid)?.data.status === 'done') updateNodeData(nid, { status: 'stale' });
      });
    },
    [getNodes, getEdges, updateNodeData],
  );

  const updateParam = useCallback(
    (id, key, value) => {
      updateNodeData(id, { [key]: value });
      markStale(id);
    },
    [updateNodeData, markStale],
  );

  const setFiles = useCallback(
    (id, key, files, meta) => {
      fileStore.set(id, files);
      updateParam(id, key, meta);
    },
    [updateParam],
  );

  const deleteNode = useCallback(
    (id) => {
      fileStore.delete(id);
      markStale(id, false);
      deleteElements({ nodes: [{ id }] });
    },
    [deleteElements, markStale],
  );

  const runNode = useCallback((id, opts) => execute([id], opts), [execute]);
  const runAll = useCallback((opts) => execute(null, opts), [execute]);

  const actions = useMemo(
    () => ({ runNode, runAll, stop, running, updateParam, setFiles, deleteNode, markStale, log }),
    [runNode, runAll, stop, running, updateParam, setFiles, deleteNode, markStale, log],
  );
  const logState = useMemo(() => ({ logs, clearLogs }), [logs, clearLogs]);

  return (
    <ActionsContext.Provider value={actions}>
      <LogsContext.Provider value={logState}>{children}</LogsContext.Provider>
    </ActionsContext.Provider>
  );
}

export const useWorkflow = () => useContext(ActionsContext);
export const useLogs = () => useContext(LogsContext);
