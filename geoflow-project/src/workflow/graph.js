export function parentsOf(id, edges) {
  return edges.filter((e) => e.target === id).map((e) => e.source);
}

export function childrenOf(id, edges) {
  return edges.filter((e) => e.source === id).map((e) => e.target);
}

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

/** The given nodes plus everything upstream of them. */
export function withAncestors(ids, edges) {
  return collect(ids, (id) => parentsOf(id, edges));
}

/** Everything downstream of the given node (excluding itself). */
export function descendantsOf(id, edges) {
  const all = collect([id], (n) => childrenOf(n, edges));
  all.delete(id);
  return all;
}

/** True if adding source→target would create a cycle. */
export function createsCycle(source, target, edges) {
  return source === target || descendantsOf(target, edges).has(source);
}

/** Topological order of `ids` (Kahn). Throws if the subgraph has a cycle. */
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

/** Stable JSON (sorted keys) so signatures don't depend on property order. */
export function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  return `{${Object.keys(value)
    .sort()
    .filter((k) => value[k] !== undefined)
    .map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`)
    .join(',')}}`;
}
