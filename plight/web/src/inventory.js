export const EQUIPMENT_SLOT_GROUPS = {
  armor: ["helm", "tunic", "pants", "sleeves", "gloves", "boots", "ring_1", "ring_2", "ring_3", "ring_4", "ring_5", "necklace_1", "necklace_2"],
  hands: ["left_hand", "right_hand"],
};

export const EQUIPMENT_SLOTS = [
  ...EQUIPMENT_SLOT_GROUPS.armor,
  ...EQUIPMENT_SLOT_GROUPS.hands,
];

export const EQUIPMENT_SLOT_LABELS = Object.fromEntries(
  EQUIPMENT_SLOTS.map((slot) => [slot, slot.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())]),
);

export function inventoryViewForSubject(subject) {
  const views = {
    inventory: "all",
    armor: "armor",
    armour: "armor",
    hands: "hands",
    weapons: "weapons",
  };
  return views[subject?.toLowerCase()] || null;
}

export function equipmentSlotsForView(view) {
  if (view === "armor") return EQUIPMENT_SLOT_GROUPS.armor;
  if (view === "hands" || view === "weapons") return EQUIPMENT_SLOT_GROUPS.hands;
  return EQUIPMENT_SLOTS;
}

export function itemCanEquip(item) {
  return (item?.equipable_slots || []).length > 0;
}

export function formatEquipmentItem(itemId, inventoryItems = []) {
  if (!itemId) return "Empty";
  if (itemId === "fist") return "Fist";
  const item = inventoryItems.find((entry) => entry.id === itemId);
  return item?.name || `${itemId.replaceAll("_", " ")} (unavailable)`;
}
