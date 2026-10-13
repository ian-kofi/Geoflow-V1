// File objects can't live in node data (it is serialized to localStorage),
// so uploaded files are kept here, keyed by node id, for the current session.
const store = new Map();

export const fileStore = {
  get: (nodeId) => store.get(nodeId) ?? [],
  set: (nodeId, files) => store.set(nodeId, files),
  delete: (nodeId) => store.delete(nodeId),
};

export function describeFiles(files) {
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
  const root = files[0]?.webkitRelativePath?.split('/')[0] || files[0]?.name || '';
  return {
    count: files.length,
    root,
    bytes: totalBytes,
    // Changes whenever the selection changes, so the node is re-run.
    signature: files.map((f) => `${f.webkitRelativePath || f.name}:${f.size}:${f.lastModified}`).join('|'),
  };
}
