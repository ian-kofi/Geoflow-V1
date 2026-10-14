/**
 * Shares the workflow actions (run, stop, change a setting, delete a node and so on) with every
 * component, so a node can run itself or update its own settings.
 */
import { createContext, useCallback, useContext, useMemo } from 'react';
import { useReactFlow } from '@xyflow/react';
import { useWorkflowRunner } from './useWorkflowRunner.js';
import { descendantsOf } from './graph.js';
import { fileStore } from './fileStore.js';

// Kept as two separate contexts so a new Console message doesn't redraw every node on the canvas.
const ActionsContext = createContext(null);
const LogsContext = createContext(null);

export function WorkflowProvider({ children }) {
  const { getNodes, getEdges, updateNodeData, deleteElements } = useReactFlow();
  const { execute, stop, running, logs, log, clearLogs } = useWorkflowRunner();

  /**
   * Marks a node (and everything after it) as out of date, because its result no longer
   * matches its settings or inputs. Only nodes that had finished are changed.
   */
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

  // Changes one setting on a node, which makes its result out of date
  const updateParam = useCallback(
    (id, key, value) => {
      updateNodeData(id, { [key]: value });
      markStale(id);
    },
    [updateNodeData, markStale],
  );

  // Stores files chosen in a node. The files themselves go in fileStore and a short
  // description of them (`meta`) goes in the node's settings.
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

/** The workflow actions, for use in any component. */
export const useWorkflow = () => useContext(ActionsContext);
/** The Console messages. */
export const useLogs = () => useContext(LogsContext);
