const OFFSETS = { north: [0, -1], south: [0, 1], east: [1, 0], west: [-1, 0] };

// Lays locations out on a grid using only their exit directions, so authored
// coordinates are never needed and boxes can never overlap.
export function layoutMap(locations, startId) {
  const byId = new Map(locations.map((location) => [location.id, location]));
  const cells = new Map();
  const taken = new Map();
  const key = (x, y) => `${x},${y}`;

  const freeNear = (x, y) => {
    for (let radius = 0; radius < 50; radius += 1) {
      for (let dx = -radius; dx <= radius; dx += 1) {
        for (let dy = -radius; dy <= radius; dy += 1) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== radius) continue;
          if (!taken.has(key(x + dx, y + dy))) return [x + dx, y + dy];
        }
      }
    }
    return [x, y];
  };
  const place = (id, x, y) => {
    const [cx, cy] = freeNear(x, y);
    cells.set(id, { x: cx, y: cy });
    taken.set(key(cx, cy), id);
  };

  const roots = [startId, ...locations.map((location) => location.id)].filter((id) => byId.has(id));
  for (const root of roots) {
    if (cells.has(root)) continue;
    const maxX = cells.size ? Math.max(...[...cells.values()].map((cell) => cell.x)) : -2;
    place(root, maxX + 2, 0);
    const queue = [root];
    while (queue.length) {
      const id = queue.shift();
      const here = cells.get(id);
      for (const [direction, destination] of Object.entries(byId.get(id).exits || {})) {
        if (!byId.has(destination) || cells.has(destination) || !OFFSETS[direction]) continue;
        place(destination, here.x + OFFSETS[direction][0], here.y + OFFSETS[direction][1]);
        queue.push(destination);
      }
      for (const other of locations) {
        if (cells.has(other.id)) continue;
        const back = Object.entries(other.exits || {}).find(([, target]) => target === id);
        if (back && OFFSETS[back[0]]) {
          place(other.id, here.x - OFFSETS[back[0]][0], here.y - OFFSETS[back[0]][1]);
          queue.push(other.id);
        }
      }
    }
  }
  return cells;
}

export function wrapLabel(name, limit = 15) {
  const lines = [];
  let line = "";
  for (const word of String(name).split(/\s+/)) {
    if (line && `${line} ${word}`.length > limit) {
      lines.push(line);
      line = word;
    } else {
      line = line ? `${line} ${word}` : word;
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}
