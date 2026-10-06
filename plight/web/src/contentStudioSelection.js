export function restoreLocationSelection(locations, currentId, storedId) {
  return locations.find((location) => location.id === currentId)?.id
    || locations.find((location) => location.id === storedId)?.id
    || locations[0]?.id
    || "";
}
