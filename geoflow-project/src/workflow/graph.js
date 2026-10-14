// Helpers for following the connections between nodes. `edges` is React Flow's list of
// connections, each with a `source` node id and a `target` node id.

/** Ids of the nodes connected into this one. */
export function parentsOf(id, edges) {
  return edges.filter((e) => e.target === id).map((e) => e.source);
}

/** Ids of the nodes this one is connected to. */
export function childrenOf(id, edges) {
  return edges.filter((e) => e.source === id).map((e) => e.target);
}

/** Every node reachable from the start nodes by repeatedly calling `next`, including the start nodes. */
function collect(startIds, next) {
  const seen = new Set();
  const stack = [...startIds];
  while (stack.length) {
    const id = stack.pop();
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...next(id));
  }
  return seen;
}

/** The given nodes plus every node that feeds into them, directly or further back. */
export function withAncestors(ids, edges) {
  return collect(ids, (id) => parentsOf(id, edges));
}

/** Every node that comes after this one, not counting itself. */
export function descendantsOf(id, edges) {
  const all = collect([id], (n) => childrenOf(n, edges));
  all.delete(id);
  return all;
}

/** True if connecting source to target would make a loop. */
export function createsCycle(source, target, edges) {
  return source === target || descendantsOf(target, edges).has(source);
}

/**
 * Puts the nodes in an order where every node comes after the ones it depends on (a
 * "topological sort", using Kahn's method). Throws if the connections form a loop.
 */
export function topoSort(ids, edges) {
  const inSet = new Set(ids);
  const relevant = edges.filter((e) => inSet.has(e.source) && inSet.has(e.target));
  const indegree = new Map([...inSet].map((id) => [id, 0]));
  relevant.forEach((e) => indegree.set(e.target, indegree.get(e.target) + 1));
  const queue = [...inSet].filter((id) => indegree.get(id) === 0);
  const order = [];
  while (queue.length) {
    const id = queue.shift();
    order.push(id);
    relevant
      .filter((e) => e.source === id)
      .forEach((e) => {
        indegree.set(e.target, indegree.get(e.target) - 1);
        if (indegree.get(e.target) === 0) queue.push(e.target);
      });
  }
  if (order.length !== inSet.size) throw new Error('The workflow contains a cycle.');
  return order;
}

/**
 * JSON with the keys always in alphabetical order. Two objects with the same contents then
 * always give the same text, which is what the runner's fingerprints rely on.
 */
export function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  return `{${Object.keys(value)
    .sort()
    .filter((k) => value[k] !== undefined)
    .map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`)
    .join(',')}}`;
}
