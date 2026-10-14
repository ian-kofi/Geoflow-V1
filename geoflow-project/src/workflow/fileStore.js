// Files chosen in nodes (Your Own File, Country Drawing). They can't be stored in the node's
// data, because that's saved in the browser as text and files can't be. So they're kept here,
// by node id, until the page is closed.
const store = new Map();

export const fileStore = {
  get: (nodeId) => store.get(nodeId) ?? [],
  set: (nodeId, files) => store.set(nodeId, files),
  delete: (nodeId) => store.delete(nodeId),
};

/** A short description of the chosen files, which is what gets saved on the node. */
export function describeFiles(files) {
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
  const root = files[0]?.webkitRelativePath?.split('/')[0] || files[0]?.name || '';
  return {
    count: files.length,
    root,
    bytes: totalBytes,
    // Changes whenever different files are chosen, so the node knows it has to run again.
    signature: files.map((f) => `${f.webkitRelativePath || f.name}:${f.size}:${f.lastModified}`).join('|'),
  };
}
