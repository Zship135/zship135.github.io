export function friendAction(status) {
  if (status === "friends") return { label: "Friends", disabled: true };
  if (status === "incoming_pending") return { label: "Accept request", disabled: false };
  if (status === "outgoing_pending") return { label: "Request sent", disabled: true };
  return { label: "Add friend", disabled: false };
}
