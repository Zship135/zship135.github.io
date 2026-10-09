import assert from "node:assert/strict";
import test from "node:test";
import { layoutMap, wrapLabel } from "./mapLayout.js";

test("layout follows exit directions and never overlaps", () => {
  const locations = [
    { id: "a", exits: { north: "b", east: "c", south: "d" } },
    { id: "b", exits: { south: "a", east: "c" } },
    { id: "c", exits: { west: "a" } },
    { id: "d", exits: { north: "a" } },
    { id: "e", exits: {} },
  ];
  const cells = layoutMap(locations, "a");
  assert.equal(cells.size, 5);
  const keys = new Set([...cells.values()].map((cell) => `${cell.x},${cell.y}`));
  assert.equal(keys.size, 5);
  const a = cells.get("a");
  assert.deepEqual(cells.get("b"), { x: a.x, y: a.y - 1 });
  assert.deepEqual(cells.get("d"), { x: a.x, y: a.y + 1 });
});

test("wrapLabel splits long names", () => {
  assert.deepEqual(wrapLabel("Old Mill"), ["Old Mill"]);
  assert.deepEqual(wrapLabel("The Forgotten Watchtower Ruins"), ["The Forgotten", "Watchtower", "Ruins"]);
});
