import assert from "node:assert/strict";
import test from "node:test";
import { friendAction } from "./playerProfile.js";

test("friend action reflects explicit request and friendship states", () => {
  assert.deepEqual(friendAction(null), { label: "Add friend", disabled: false });
  assert.deepEqual(friendAction("outgoing_pending"), { label: "Request sent", disabled: true });
  assert.deepEqual(friendAction("incoming_pending"), { label: "Accept request", disabled: false });
  assert.deepEqual(friendAction("friends"), { label: "Friends", disabled: true });
});
