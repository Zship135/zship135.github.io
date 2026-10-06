import assert from "node:assert/strict";
import test from "node:test";
import { restoreLocationSelection } from "./contentStudioSelection.js";

test("restores the previously selected location after a content reload", () => {
  const locations = [{ id: "first" }, { id: "seventh" }];

  assert.equal(restoreLocationSelection(locations, "", "seventh"), "seventh");
});

test("keeps the current location and falls back when it was removed", () => {
  const locations = [{ id: "first" }, { id: "seventh" }];

  assert.equal(restoreLocationSelection(locations, "seventh", "first"), "seventh");
  assert.equal(restoreLocationSelection(locations, "removed", "missing"), "first");
});
