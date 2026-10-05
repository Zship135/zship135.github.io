import assert from "node:assert/strict";
import test from "node:test";
import {
  EQUIPMENT_SLOTS,
  equipmentSlotsForView,
  formatEquipmentItem,
  inventoryViewForSubject,
  itemCanEquip,
} from "./inventory.js";

test("inventory observation selects the requested menu view", () => {
  assert.equal(inventoryViewForSubject("inventory"), "all");
  assert.equal(inventoryViewForSubject("armor"), "armor");
  assert.equal(inventoryViewForSubject("hands"), "hands");
  assert.equal(inventoryViewForSubject("weapons"), "hands");
  assert.equal(inventoryViewForSubject("dragon"), null);
});

test("inventory menu exposes every requested equipment slot", () => {
  assert.deepEqual(EQUIPMENT_SLOTS, [
    "helm", "tunic", "pants", "sleeves", "gloves", "boots",
    "ring_1", "ring_2", "ring_3", "ring_4", "ring_5",
    "necklace_1", "necklace_2", "left_hand", "right_hand",
  ]);
  assert.deepEqual(equipmentSlotsForView("armor"), EQUIPMENT_SLOTS.slice(0, 13));
  assert.deepEqual(equipmentSlotsForView("hands"), ["left_hand", "right_hand"]);
  assert.deepEqual(equipmentSlotsForView("weapons"), ["left_hand", "right_hand"]);
  assert.deepEqual(equipmentSlotsForView(inventoryViewForSubject("weapons")), ["left_hand", "right_hand"]);
});

test("items without an equipment definition remain non-equippable", () => {
  assert.equal(itemCanEquip({ equipable_slots: ["left_hand"] }), true);
  assert.equal(itemCanEquip({ equipable_slots: [] }), false);
  assert.equal(formatEquipmentItem("iron_sword", [{ id: "iron_sword", name: "Iron sword" }]), "Iron sword");
  assert.equal(formatEquipmentItem("missing_item"), "missing item (unavailable)");
});
