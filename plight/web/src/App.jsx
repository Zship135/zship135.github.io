import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiBlob, liveUrl } from "./api.js";
import ContentStudio from "./ContentStudio.jsx";
import { friendAction } from "./playerProfile.js";
import {
  EQUIPMENT_SLOT_GROUPS,
  EQUIPMENT_SLOT_LABELS,
  equipmentSlotsForView,
  formatEquipmentItem,
  itemCanEquip,
} from "./inventory.js";

const TOKEN_KEY = "plight.session";
const ACCOUNT_KEY = "plight.account";

function pendingCommandsKey(accountId) {
  return `plight.pendingCommands.${accountId}`;
}

function loadPendingCommands(accountId) {
  if (!accountId) return [];
  const saved = sessionStorage.getItem(pendingCommandsKey(accountId));
  if (!saved) return [];
  const value = JSON.parse(saved);
  if (!Array.isArray(value) || value.some((item) => !item.request_id || !item.text)) {
    throw new Error("Saved command recovery data is invalid. Clear this tab's site data and sign in again.");
  }
  return value;
}

function removePendingCommand(accountId, requestId) {
  if (!accountId) return;
  const remaining = loadPendingCommands(accountId).filter(
    (item) => item.request_id !== requestId,
  );
  sessionStorage.setItem(pendingCommandsKey(accountId), JSON.stringify(remaining));
}

function upsertActivity(current, entry) {
  if (!entry.request_id) return [...current, entry].slice(-30);
  const existingIndex = current.findIndex((item) => item.request_id === entry.request_id);
  if (existingIndex === -1) return [...current, entry].slice(-30);
  return current.map((item, index) => index === existingIndex ? entry : item);
}

function activityMessageClass(message, entry) {
  if (entry.type === "location") return "world-text";
  if (entry.type === "enemy") return "enemy-text";
  if (/^(You gain \d+ experience\.|Loot:|No items dropped\.)/i.test(message)) return "reward-text";
  if (/\brolls D\d+\b|\bhits you for\b|\bis defeated\b/i.test(message)) return "enemy-text";
  return "player-text";
}

function ChatPanel({ activeChannel, channels, messages, onClose, onSelect, onSend, onPrivateChat }) {
  const [text, setText] = useState("");
  const displayName = (channel) => channel.label;
  const partyChannel = activeChannel.id.startsWith("party:");

  function submit(event) {
    event.preventDefault();
    const message = text.trim();
    if (!message) return;
    onSend(activeChannel.id, message);
    setText("");
  }

  return (
    <section className="panel chat-panel" aria-label="Chat">
      <div className="chat-tabs" role="tablist" aria-label="Chat channels">
        {channels.map((channel) => (
          <div className="chat-tab-wrap" key={channel.id}>
            <button
              aria-selected={channel.id === activeChannel.id}
              className={`chat-tab ${channel.id === activeChannel.id ? "selected" : ""}`}
              onClick={() => onSelect(channel.id)}
              role="tab"
            >
              {displayName(channel)}
            </button>
            {channel.id.startsWith("private:") && (
              <button
                aria-label={`Close ${channel.label} chat`}
                className="close-tab"
                onClick={() => onClose(channel.id)}
                type="button"
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="chat-messages" aria-live="polite">
        {messages.length === 0 ? (
          <p className="empty-state">No messages yet. Say hello to the world.</p>
        ) : messages.map((message) => (
          <article className={`chat-message ${partyChannel ? "party-chat-message" : "player-chat-message"}`} key={message.message_id}>
            <time>{new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
            <button
              className="sender-link"
              onClick={() => onPrivateChat(message.sender_account_id, message.sender)}
              title={`Open ${message.sender}'s profile`}
              type="button"
            >
              {message.sender}
            </button>
            <p>{message.text}</p>
          </article>
        ))}
      </div>
      <form className="chat-compose" onSubmit={submit}>
        <label className="sr-only" htmlFor="chat-input">Write a chat message</label>
        <input
          autoComplete="off"
          id="chat-input"
          maxLength={1000}
          onChange={(event) => setText(event.target.value)}
          placeholder={`Message ${activeChannel.label.toLowerCase()}…`}
          value={text}
        />
        <button className="send-button" disabled={!text.trim()} type="submit" aria-label="Send message">↗</button>
      </form>
    </section>
  );
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY));
  const [accountId, setAccountId] = useState(() => sessionStorage.getItem(ACCOUNT_KEY));
  const [authMode, setAuthMode] = useState("login");
  const [authError, setAuthError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [confirmPassword, setConfirmPassword] = useState("");
  const [form, setForm] = useState({ email: "", password: "" });
  const [snapshot, setSnapshot] = useState(null);
  const [ambienceEvents, setAmbienceEvents] = useState([]);
  const [characterSetupPending, setCharacterSetupPending] = useState(false);
  const [characterForm, setCharacterForm] = useState({
    name: "",
    species: "human",
    appearance: {
      build: "average",
      complexion: "tan",
      hair_style: "short",
      hair_color: "brown",
      eye_color: "brown",
    },
  });
  const [characterError, setCharacterError] = useState("");
  const [characterBusy, setCharacterBusy] = useState(false);
  const [activity, setActivity] = useState([]);
  const [dialogueBusyKey, setDialogueBusyKey] = useState("");
  const [questBusyId, setQuestBusyId] = useState("");
  const [canEditContent, setCanEditContent] = useState(false);
  const [studioMode, setStudioMode] = useState(false);
  const [channels, setChannels] = useState([{ id: "global", label: "World" }]);
  const [activeChannelId, setActiveChannelId] = useState("global");
  const [messagesByChannel, setMessagesByChannel] = useState({});
  const [partyState, setPartyState] = useState({
    party: null,
    incoming_invitations: [],
    outgoing_invitations: [],
  });
  const [partyBusy, setPartyBusy] = useState(false);
  const [profile, setProfile] = useState(null);
  const [profileForm, setProfileForm] = useState({ pronouns: "", lore: "" });
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [peopleOpen, setPeopleOpen] = useState(false);
  const [peopleBusy, setPeopleBusy] = useState(false);
  const [peopleError, setPeopleError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [playerResults, setPlayerResults] = useState([]);
  const [friendList, setFriendList] = useState([]);
  const [incomingRequests, setIncomingRequests] = useState([]);
  const [directoryPictureUrls, setDirectoryPictureUrls] = useState({});
  const [command, setCommand] = useState("");
  const [commandBusy, setCommandBusy] = useState(false);
  const [inventoryView, setInventoryView] = useState(null);
  const [notice, setNotice] = useState("");
  const socketRef = useRef(null);
  const activityScrollRef = useRef(null);
  const followActivityRef = useRef(true);
  const previousAreaIdRef = useRef(null);
  const ambienceSequenceRef = useRef(0);
  const seenPartyInvitationIdsRef = useRef(new Set());
  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;
  const recoveringCommandsRef = useRef(false);
  const profilePictureUrlRef = useRef(null);
  const channelsRef = useRef(channels);
  channelsRef.current = channels;
  const activeChannelIdRef = useRef(activeChannelId);
  activeChannelIdRef.current = activeChannelId;
  const activeChannel = useMemo(
    () => channels.find((channel) => channel.id === activeChannelId) || channels[0],
    [activeChannelId, channels],
  );
  const messages = messagesByChannel[activeChannel.id] || [];
  const partyChannelId = partyState.party?.channel_id || null;

  useEffect(() => {
    setChannels((current) => {
      const next = current.filter(
        (channel) => !channel.id.startsWith("party:") || channel.id === partyChannelId,
      );
      if (partyChannelId && !next.some((channel) => channel.id === partyChannelId)) {
        next.push({ id: partyChannelId, label: "Party" });
      }
      return next;
    });
    setActiveChannelId((current) => (
      current.startsWith("party:") && current !== partyChannelId
        ? partyChannelId || "global"
        : current
    ));
  }, [partyChannelId]);

  useEffect(() => {
    if (!token) {
      setCanEditContent(false);
      setStudioMode(false);
      return;
    }
    api("/api/v1/content/permission", { token })
      .then((result) => setCanEditContent(result.can_edit))
      .catch(showError);
  }, [token]);

  useEffect(() => () => {
    if (profilePictureUrlRef.current) URL.revokeObjectURL(profilePictureUrlRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadedUrls = [];
    async function loadDirectoryPictures() {
      const pairs = await Promise.all(playerResults.map(async (player) => {
        if (!player.profile_picture_url) return [player.account_id, null];
        try {
          const image = await apiBlob(player.profile_picture_url, { token });
          const url = URL.createObjectURL(image);
          loadedUrls.push(url);
          return [player.account_id, url];
        } catch {
          return [player.account_id, null];
        }
      }));
      if (!cancelled) setDirectoryPictureUrls(Object.fromEntries(pairs.filter(([, url]) => url)));
      else loadedUrls.forEach((url) => URL.revokeObjectURL(url));
    }
    setDirectoryPictureUrls({});
    if (token && playerResults.length) loadDirectoryPictures();
    return () => {
      cancelled = true;
      loadedUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [playerResults, token]);

  useEffect(() => {
    if (!snapshot?.area?.id) return undefined;
    const world = snapshotRef.current;
    const authoredLines = world.area.ambience_lines || [];
    const lines = authoredLines.length
      ? authoredLines
      : [world.atmosphere?.sounds || "The area is quiet."];
    const createEvent = () => ({
      id: `${world.area.id}-${ambienceSequenceRef.current++}`,
      text: lines[Math.floor(Math.random() * lines.length)],
    });
    const initialCount = Math.min(3, lines.length);
    setAmbienceEvents(Array.from({ length: initialCount }, createEvent));
    const timer = window.setInterval(() => {
      setAmbienceEvents((current) => [...current, createEvent()].slice(-6));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [snapshot?.area?.id]);

  useEffect(() => {
    const areaId = snapshot?.character?.area_id;
    if (!areaId || previousAreaIdRef.current === areaId) return;
    previousAreaIdRef.current = areaId;
    followActivityRef.current = true;
    setActivity([{
      id: `location:${areaId}`,
      type: "location",
      text: snapshot.area?.description || "You arrive in a new location.",
    }]);
  }, [snapshot?.character?.area_id, snapshot?.area?.description]);

  useEffect(() => {
    const stream = activityScrollRef.current;
    if (!stream || !followActivityRef.current) return;
    stream.scrollTop = stream.scrollHeight;
  }, [activity]);

  const refreshWorld = useCallback(async (sessionToken) => {
    let world;
    try {
      world = await api("/api/v1/world/snapshot", { token: sessionToken });
    } catch (error) {
      if (error.status === 409) {
        setCharacterSetupPending(true);
        setSnapshot(null);
        return null;
      }
      throw error;
    }
    setSnapshot(world);
    setCharacterSetupPending(false);
    setAccountId(world.account_id);
    sessionStorage.setItem(ACCOUNT_KEY, world.account_id);
    return world;
  }, []);

  const refreshParty = useCallback(async (sessionToken) => {
    const current = await api("/api/v1/party", { token: sessionToken });
    const unseenInvitations = current.incoming_invitations.filter(
      (invitation) => !seenPartyInvitationIdsRef.current.has(invitation.invite_id),
    );
    current.incoming_invitations.forEach((invitation) => {
      seenPartyInvitationIdsRef.current.add(invitation.invite_id);
    });
    if (unseenInvitations.length) {
      const inviter = unseenInvitations[0].player?.name || "A player";
      setNotice(`${inviter} invited you to a party.`);
    }
    setPartyState(current);
    return current;
  }, []);

  const refreshMessages = useCallback(async (sessionToken, channelId) => {
    const result = await api(`/api/v1/chat/${encodeURIComponent(channelId)}/messages`, { token: sessionToken });
    setMessagesByChannel((current) => ({ ...current, [channelId]: result.messages }));
  }, []);

  const recoverCommands = useCallback(async (sessionToken, ownerAccountId) => {
    if (recoveringCommandsRef.current) return;
    recoveringCommandsRef.current = true;
    try {
      const pending = loadPendingCommands(ownerAccountId);
      for (const item of pending) {
        let result;
        try {
          result = await api(`/api/v1/commands/${item.request_id}`, { token: sessionToken });
        } catch (error) {
          if (error.status !== 404) throw error;
          result = await api("/api/v1/commands", {
            token: sessionToken,
            method: "POST",
            body: JSON.stringify(item),
          });
        }
        if (result.status === "queued") continue;
        setActivity((current) => upsertActivity(current, result));
        await refreshWorld(sessionToken);
        const remaining = loadPendingCommands(ownerAccountId).filter((entry) => entry.request_id !== item.request_id);
        sessionStorage.setItem(pendingCommandsKey(ownerAccountId), JSON.stringify(remaining));
      }
    } catch (error) {
      showError(error);
    } finally {
      recoveringCommandsRef.current = false;
    }
  }, [refreshWorld]);

  const openPrivateChat = useCallback((accountId, name) => {
    if (!snapshot || !accountId || accountId === snapshot.account_id) return;
    const participants = [snapshot.account_id, accountId].filter(Boolean).sort();
    const ownAccountId = snapshot.account_id;
    if (!ownAccountId) return;
    const channelId = `private:${participants.join(":")}`;
    setChannels((current) => current.some((item) => item.id === channelId)
      ? current
      : [...current, { id: channelId, label: name }]);
    setActiveChannelId(channelId);
    setProfile(null);
    if (profilePictureUrlRef.current) {
      URL.revokeObjectURL(profilePictureUrlRef.current);
      profilePictureUrlRef.current = null;
    }
  }, [snapshot]);

  function closeProfile() {
    setProfile(null);
    if (profilePictureUrlRef.current) {
      URL.revokeObjectURL(profilePictureUrlRef.current);
      profilePictureUrlRef.current = null;
    }
  }

  function closePeople() {
    setPeopleOpen(false);
    setPlayerResults([]);
    setSearchQuery("");
    setDirectoryPictureUrls({});
  }

  async function showProfile(profileData) {
    let nextProfile = { ...profileData, picture_src: null };
    if (profileData.profile_picture_url) {
      const image = await apiBlob(profileData.profile_picture_url, { token });
      const objectUrl = URL.createObjectURL(image);
      if (profilePictureUrlRef.current) URL.revokeObjectURL(profilePictureUrlRef.current);
      profilePictureUrlRef.current = objectUrl;
      nextProfile.picture_src = objectUrl;
    } else if (profilePictureUrlRef.current) {
      URL.revokeObjectURL(profilePictureUrlRef.current);
      profilePictureUrlRef.current = null;
    }
    setProfile(nextProfile);
    setProfileError("");
  }

  async function openOwnProfile() {
    try {
      const result = await api("/api/v1/profile", { token });
      setProfileForm({ pronouns: result.pronouns || "", lore: result.lore || "" });
      await showProfile(result);
    } catch (error) {
      showError(error);
    }
  }

  async function openPlayerProfile(playerAccountId, equippedGear = null) {
    setPeopleOpen(false);
    if (playerAccountId === snapshot?.account_id) {
      await openOwnProfile();
      return;
    }
    try {
      const result = await api(`/api/v1/players/${encodeURIComponent(playerAccountId)}/profile`, { token });
      await showProfile(equippedGear ? { ...result, equipped_gear: equippedGear } : result);
    } catch (error) {
      showError(error);
    }
  }

  async function openPeople() {
    setPeopleOpen(true);
    setPeopleError("");
    setPeopleBusy(true);
    try {
      const [friendsResult, requestsResult, currentParty] = await Promise.all([
        api("/api/v1/friends", { token }),
        api("/api/v1/friend-requests", { token }),
        refreshParty(token),
      ]);
      setFriendList(friendsResult);
      setIncomingRequests(requestsResult.incoming);
      setPartyState(currentParty);
    } catch (error) {
      setPeopleError(error.message);
    } finally {
      setPeopleBusy(false);
    }
  }

  async function searchPlayers(event) {
    event.preventDefault();
    if (!searchQuery.trim()) {
      setPlayerResults([]);
      return;
    }
    setPeopleBusy(true);
    setPeopleError("");
    try {
      const results = await api(`/api/v1/players?q=${encodeURIComponent(searchQuery.trim())}`, { token });
      setPlayerResults(results);
    } catch (error) {
      setPeopleError(error.message);
    } finally {
      setPeopleBusy(false);
    }
  }

  async function requestFriend(player) {
    setPeopleBusy(true);
    setPeopleError("");
    try {
      if (player.friend_status === "incoming_pending") {
        const requests = await api("/api/v1/friend-requests", { token });
        const request = requests.incoming.find((item) => item.player?.account_id === player.account_id);
        if (request) {
          await api(`/api/v1/friend-requests/${request.request_id}`, {
            token,
            method: "PATCH",
            body: JSON.stringify({ status: "accepted" }),
          });
        }
      } else {
        await api("/api/v1/friend-requests", {
          token,
          method: "POST",
          body: JSON.stringify({ recipient_account_id: player.account_id }),
        });
      }
      const [results, friendsResult, requestsResult] = await Promise.all([
        api(`/api/v1/players?q=${encodeURIComponent(searchQuery.trim())}`, { token }),
        api("/api/v1/friends", { token }),
        api("/api/v1/friend-requests", { token }),
      ]);
      setPlayerResults(results);
      setFriendList(friendsResult);
      setIncomingRequests(requestsResult.incoming);
    } catch (error) {
      setPeopleError(error.message);
    } finally {
      setPeopleBusy(false);
    }
  }

  async function createParty() {
    setPartyBusy(true);
    setPeopleError("");
    try {
      const updated = await api("/api/v1/party", { token, method: "POST" });
      setPartyState(updated);
      if (updated.party) setActiveChannelId(updated.party.channel_id);
      setNotice("Your party is ready. Open a player's profile to invite them.");
    } catch (error) {
      setPeopleError(error.message);
    } finally {
      setPartyBusy(false);
    }
  }

  async function invitePlayerToParty(accountId, name) {
    setPartyBusy(true);
    setProfileError("");
    try {
      let current = await refreshParty(token);
      if (!current.party) {
        current = await api("/api/v1/party", { token, method: "POST" });
        setPartyState(current);
      }
      if (current.party?.leader_account_id !== snapshot?.account_id) {
        throw new Error("Only your party's leader can invite players.");
      }
      const updated = await api("/api/v1/party/invitations", {
        token,
        method: "POST",
        body: JSON.stringify({ recipient_account_id: accountId }),
      });
      setPartyState(updated);
      if (updated.party) setActiveChannelId(updated.party.channel_id);
      closeProfile();
      setNotice(`Party invitation sent to ${name}.`);
    } catch (error) {
      setProfileError(error.message);
    } finally {
      setPartyBusy(false);
    }
  }

  async function respondToPartyInvite(invitation, status) {
    setPartyBusy(true);
    setPeopleError("");
    try {
      const updated = await api(`/api/v1/party/invitations/${encodeURIComponent(invitation.invite_id)}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setPartyState(updated);
      if (status === "accepted" && updated.party) {
        setActiveChannelId(updated.party.channel_id);
      }
    } catch (error) {
      setPeopleError(error.message);
    } finally {
      setPartyBusy(false);
    }
  }

  async function performPartyAction(path, method, confirmation, successMessage) {
    if (confirmation && !window.confirm(confirmation)) return;
    setPartyBusy(true);
    setPeopleError("");
    try {
      const updated = await api(path, { token, method });
      setPartyState(updated);
      if (updated.party) setActiveChannelId(updated.party.channel_id);
      if (successMessage) setNotice(successMessage);
    } catch (error) {
      setPeopleError(error.message);
    } finally {
      setPartyBusy(false);
    }
  }

  async function saveProfile(event) {
    event.preventDefault();
    setProfileBusy(true);
    setProfileError("");
    try {
      const updated = await api("/api/v1/profile", {
        token,
        method: "PUT",
        body: JSON.stringify(profileForm),
      });
      await showProfile(updated);
    } catch (error) {
      setProfileError(error.message);
    } finally {
      setProfileBusy(false);
    }
  }

  async function uploadProfilePicture(file) {
    if (!file) return;
    setProfileBusy(true);
    setProfileError("");
    try {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 512 * 1024) {
        throw new Error("Choose a PNG, JPEG, or WebP image no larger than 512 KiB.");
      }
      const uploaded = await api("/api/v1/profile/picture", {
        token,
        method: "PUT",
        body: file,
        headers: { "Content-Type": file.type },
      });
      await showProfile(uploaded);
    } catch (error) {
      setProfileError(error.message);
    } finally {
      setProfileBusy(false);
    }
  }

  async function removeProfilePicture() {
    setProfileBusy(true);
    setProfileError("");
    try {
      await api("/api/v1/profile/picture", { token, method: "DELETE" });
      const updated = await api("/api/v1/profile", { token });
      await showProfile(updated);
    } catch (error) {
      setProfileError(error.message);
    } finally {
      setProfileBusy(false);
    }
  }

  function showError(error) {
    if (error.status === 401) {
      sessionStorage.removeItem(TOKEN_KEY);
      setToken(null);
      sessionStorage.removeItem(ACCOUNT_KEY);
      setAccountId(null);
      setPartyState({ party: null, incoming_invitations: [], outgoing_invitations: [] });
      seenPartyInvitationIdsRef.current.clear();
    }
    setNotice(error.message);
  }

  async function submitAuth(event) {
    event.preventDefault();
    setAuthError("");
    if (authMode === "register" && form.password !== confirmPassword) {
      setAuthError("Passwords do not match.");
      return;
    }
    setAuthBusy(true);
    try {
      if (authMode === "register") {
        await api("/api/v1/auth/register", {
          method: "POST",
          body: JSON.stringify(form),
        });
        setAuthMode("login");
        setForm((current) => ({ ...current, password: "" }));
        setConfirmPassword("");
        setAuthNotice("Account created. Sign in to create your character.");
        return;
      }
      const result = await api("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify(form),
      });
      setCharacterSetupPending(false);
      sessionStorage.setItem(TOKEN_KEY, result.token);
      sessionStorage.setItem(ACCOUNT_KEY, result.account_id);
      setToken(result.token);
      setAccountId(result.account_id);
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setAuthBusy(false);
    }
  }

  useEffect(() => {
    if (!token || characterSetupPending) return undefined;
    let cancelled = false;
    let reconnectTimer;
    let retryDelay = 1000;

    async function connect() {
      try {
        const world = await refreshWorld(token);
        if (!world) {
          return;
        }
      } catch (error) {
        if (!cancelled) showError(error);
        return;
      }
      if (cancelled) return;
      const socket = new WebSocket(liveUrl());
      socketRef.current = socket;
      socket.onopen = () => socket.send(JSON.stringify({ type: "auth", token }));
      socket.onmessage = async (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch {
          setNotice("The live connection sent an unreadable update.");
          socket.close();
          return;
        }
        if (data.type === "auth.ok") {
          retryDelay = 1000;
          for (const channel of channelsRef.current) {
            socket.send(JSON.stringify({ type: "subscribe", channel_id: channel.id }));
          }
          const world = await refreshWorld(token);
          await refreshParty(token);
          socket.send(JSON.stringify({
            type: "subscribe",
            channel_id: `account:${world.account_id}`,
          }));
          await refreshMessages(token, "global");
          if (activeChannelIdRef.current !== "global") {
            await refreshMessages(token, activeChannelIdRef.current);
          }
          await recoverCommands(token, world.account_id);
          return;
        }
        if (data.type === "subscribed") {
          if (data.channel_id.startsWith("account:")) return;
          await refreshMessages(token, data.channel_id);
          return;
        }
        if (data.type === "party.updated") {
          await refreshParty(token);
          const world = await refreshWorld(token);
          if (!world) socket.close();
          return;
        }
        if (data.type === "chat.message") {
          const message = data.payload;
          setMessagesByChannel((current) => {
            const existing = current[message.channel_id] || [];
            if (existing.some((item) => item.message_id === message.message_id)) return current;
            return { ...current, [message.channel_id]: [...existing, message].slice(-50) };
          });
        }
        if (data.type === "command.updated") {
          setActivity((current) => upsertActivity(current, data.payload));
          await refreshWorld(token);
          return;
        }
        if (data.type === "command.completed") {
          setActivity((current) => upsertActivity(current, data.payload));
          try {
            removePendingCommand(accountId, data.payload.request_id);
          } catch (error) {
            showError(error);
          }
          const world = await refreshWorld(token);
          if (!world) {
            socket.close();
            return;
          }
        }
        if (data.type === "world.updated") {
          const update = data.payload || {};
          if (update.messages?.length) {
            setActivity((current) => [
              ...current,
              {
                id: update.id || `world-update-${Date.now()}`,
                type: "enemy",
                result: { messages: update.messages },
              },
            ].slice(-30));
          }
          const world = await refreshWorld(token);
          if (!world) {
            socket.close();
            return;
          }
        }
        if (data.type === "quest.updated") {
          await refreshWorld(token);
        }
      };
      socket.onclose = () => {
        if (cancelled) return;
        reconnectTimer = window.setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 30000);
          connect();
        }, retryDelay);
      };
      socket.onerror = () => socket.close();
    }

    connect();
    return () => {
      cancelled = true;
      window.clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [token, accountId, characterSetupPending, refreshWorld, refreshParty, refreshMessages, recoverCommands]);

  useEffect(() => {
    if (!token || characterSetupPending || !activeChannel) return;
    refreshMessages(token, activeChannel.id).catch(showError);
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "subscribe", channel_id: activeChannel.id }));
    }
  }, [token, characterSetupPending, activeChannel, refreshMessages]);

  async function submitCharacter(event) {
    event.preventDefault();
    setCharacterError("");
    setCharacterBusy(true);
    try {
      await api("/api/v1/characters", {
        token,
        method: "POST",
        body: JSON.stringify(characterForm),
      });
      await refreshWorld(token);
    } catch (error) {
      setCharacterError(error.message);
    } finally {
      setCharacterBusy(false);
    }
  }

  async function runCommand(text) {
    text = text.trim();
    if (!text || commandBusy) return;
    setCommandBusy(true);
    setNotice("");
    const request = { request_id: crypto.randomUUID(), text };
    try {
      if (!accountId) throw new Error("Your character is still loading. Try again shortly.");
      const pending = loadPendingCommands(accountId);
      sessionStorage.setItem(pendingCommandsKey(accountId), JSON.stringify([...pending, request]));
      const result = await api("/api/v1/commands", {
        token,
        method: "POST",
        body: JSON.stringify(request),
      });
      if (result.status !== "queued") {
        removePendingCommand(accountId, request.request_id);
      }
      setActivity((current) => upsertActivity(current, result));
      if (result.result?.inventory_view) setInventoryView(result.result.inventory_view);
      const observedAccountId = result.result?.profile_account_ids?.[0];
      if (observedAccountId) {
        await openPlayerProfile(
          observedAccountId,
          result.result?.observed_player_equipment?.[observedAccountId],
        );
      }
      if (text === command.trim()) setCommand("");
      await refreshWorld(token);
    } catch (error) {
      showError(error);
    } finally {
      setCommandBusy(false);
    }

  }

  async function submitCommand(event) {
    event.preventDefault();
    await runCommand(command);
  }

  function enterCommand(text) {
    setCommand(text);
    document.getElementById("command-input")?.focus();
  }

  async function selectDialogueChoice(entry, dialogue, choice) {
    const busyKey = `${entry.request_id}:${dialogue.occurrence_id}`;
    setDialogueBusyKey(busyKey);
    setNotice("");
    try {
      const nextNode = await api("/api/v1/dialogue/choice", {
        token,
        method: "POST",
        body: JSON.stringify({
          npc_id: dialogue.npc_id,
          node_id: dialogue.node_id,
          choice_id: choice.id,
        }),
      });
      setActivity((current) => current.map((currentEntry) => {
        if (currentEntry.request_id !== entry.request_id) return currentEntry;
        const dialogues = (currentEntry.result?.dialogues || []).map((currentDialogue) => {
          if (currentDialogue.occurrence_id !== dialogue.occurrence_id) return currentDialogue;
          return {
            ...nextNode,
            occurrence_id: currentDialogue.occurrence_id,
            history: [
              ...(currentDialogue.history || []),
              { speaker: "You", text: choice.text },
              { speaker: nextNode.npc_name, text: nextNode.text },
            ],
          };
        });
        return { ...currentEntry, result: { ...currentEntry.result, dialogues } };
      }));
    } catch (error) {
      showError(error);
    } finally {
      setDialogueBusyKey("");
    }
  }

  async function runQuestAction(quest, action, body) {
    setQuestBusyId(quest.id);
    setNotice("");
    try {
      const result = await api(`/api/v1/quests/${encodeURIComponent(quest.id)}/${action}`, {
        token,
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      setSnapshot(result.snapshot);
      const messages = result.messages || [result.message];
      setActivity((current) => [
        ...current,
        {
          id: `quest-${quest.id}-${Date.now()}`,
          type: "quest",
          result: { messages },
        },
      ].slice(-30));
    } catch (error) {
      showError(error);
      try {
        await refreshWorld(token);
      } catch (refreshError) {
        showError(refreshError);
      }
    } finally {
      setQuestBusyId("");
    }
  }

  async function sendChat(channelId, text) {
    try {
      const sent = await api("/api/v1/chat/messages", {
        token,
        method: "POST",
        body: JSON.stringify({ channel_id: channelId, text }),
      });
      const message = { ...sent, sender_account_id: snapshot?.account_id };
      setMessagesByChannel((current) => {
        const existing = current[channelId] || [];
        if (existing.some((item) => item.message_id === message.message_id)) return current;
        return { ...current, [channelId]: [...existing, message].slice(-50) };
      });
    } catch (error) {
      showError(error);
    }
  }

  async function signOut() {
    try {
      await api("/api/v1/auth/logout", { token, method: "POST" });
    } catch (error) {
      if (error.status !== 401) setNotice(error.message);
    } finally {
      sessionStorage.removeItem(TOKEN_KEY);
      setToken(null);
      setCanEditContent(false);
      setStudioMode(false);
      setSnapshot(null);
      setCharacterSetupPending(false);
      sessionStorage.removeItem(ACCOUNT_KEY);
      setAccountId(null);
      setForm({ email: "", password: "" });
      setConfirmPassword("");
      setAuthMode("login");
      setAuthError("");
      setAuthNotice("");
      setChannels([{ id: "global", label: "World" }]);
      setActiveChannelId("global");
      setMessagesByChannel({});
      setPartyState({ party: null, incoming_invitations: [], outgoing_invitations: [] });
      seenPartyInvitationIdsRef.current.clear();
      setActivity([]);
      setInventoryView(null);
      previousAreaIdRef.current = null;
      setAmbienceEvents([]);
      setProfile(null);
    }
  }

  function closeChannel(channelId) {
    setChannels((current) => current.filter((channel) => channel.id !== channelId));
    setMessagesByChannel((current) => {
      const { [channelId]: _removed, ...remaining } = current;
      return remaining;
    });
    if (activeChannelId === channelId) setActiveChannelId("global");
  }

  if (!token) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <a className="wordmark" href="#top">PLIGHT</a>
          <form className="auth-form" onSubmit={submitAuth}>
            <label>Email address<input autoComplete="email" onChange={(event) => setForm({ ...form, email: event.target.value })} required type="email" value={form.email} /></label>
            <label>Password<input autoComplete={authMode === "register" ? "new-password" : "current-password"} minLength={authMode === "register" ? 12 : 1} onChange={(event) => setForm({ ...form, password: event.target.value })} required type="password" value={form.password} /></label>
            {authMode === "register" && (
              <label>Confirm password<input autoComplete="new-password" maxLength={128} minLength={12} onChange={(event) => setConfirmPassword(event.target.value)} required type="password" value={confirmPassword} /></label>
            )}
            {authNotice && <p className="success-message" role="status">{authNotice}</p>}
            {authError && <p className="error-message" role="alert">{authError}</p>}
            <button className="primary-button" disabled={authBusy} type="submit">{authBusy ? "One moment…" : authMode === "register" ? "Create account" : "Enter the world"}</button>
          </form>
          <button className="text-button auth-switch" onClick={() => { setAuthError(""); setAuthNotice(""); setConfirmPassword(""); setAuthMode(authMode === "login" ? "register" : "login"); }} type="button">
            {authMode === "login" ? "Make a New Account" : "Already have an account? Sign in"}
          </button>
        </section>
      </main>
    );
  }

  if (studioMode && canEditContent) {
    return (
      <ContentStudio
        onClose={() => {
          setStudioMode(false);
          refreshWorld(token).catch(showError);
        }}
        onSignOut={signOut}
        token={token}
      />
    );
  }

  if (characterSetupPending) {
    return (
      <main className="auth-screen">
        <section className="auth-card character-setup-card">
          <a className="wordmark" href="#top">PLIGHT</a>
          <header className="character-heading">
            <p className="eyebrow">CHARACTER CREATION</p>
            <h1>Create your character</h1>
            <p>Choose a name, race, and appearance. Appearance is cosmetic only.</p>
          </header>
          <form className="character-form" onSubmit={submitCharacter}>
            <label>Character name<input autoComplete="off" maxLength={32} minLength={2} onChange={(event) => setCharacterForm((current) => ({ ...current, name: event.target.value }))} required value={characterForm.name} /></label>
            <label>Race<select onChange={(event) => setCharacterForm((current) => ({ ...current, species: event.target.value }))} value={characterForm.species}><option value="human">Human</option><option value="goblin">Goblin</option></select></label>
            <fieldset className="appearance-fields">
              <legend>Appearance</legend>
              <label>Build<select onChange={(event) => setCharacterForm((current) => ({ ...current, appearance: { ...current.appearance, build: event.target.value } }))} value={characterForm.appearance.build}><option value="slender">Slender</option><option value="average">Average</option><option value="broad">Broad</option><option value="stocky">Stocky</option></select></label>
              <label>Complexion<select onChange={(event) => setCharacterForm((current) => ({ ...current, appearance: { ...current.appearance, complexion: event.target.value } }))} value={characterForm.appearance.complexion}><option value="pale">Pale</option><option value="light">Light</option><option value="olive">Olive</option><option value="tan">Tan</option><option value="brown">Brown</option><option value="deep">Deep</option></select></label>
              <label>Hair style<select onChange={(event) => setCharacterForm((current) => ({ ...current, appearance: { ...current.appearance, hair_style: event.target.value } }))} value={characterForm.appearance.hair_style}><option value="short">Short</option><option value="long">Long</option><option value="tied_back">Tied back</option><option value="braided">Braided</option><option value="bald">Bald</option></select></label>
              <label>Hair color<select onChange={(event) => setCharacterForm((current) => ({ ...current, appearance: { ...current.appearance, hair_color: event.target.value } }))} value={characterForm.appearance.hair_color}><option value="black">Black</option><option value="brown">Brown</option><option value="blond">Blond</option><option value="red">Red</option><option value="gray">Gray</option><option value="white">White</option></select></label>
              <label>Eye color<select onChange={(event) => setCharacterForm((current) => ({ ...current, appearance: { ...current.appearance, eye_color: event.target.value } }))} value={characterForm.appearance.eye_color}><option value="brown">Brown</option><option value="blue">Blue</option><option value="green">Green</option><option value="gray">Gray</option><option value="amber">Amber</option></select></label>
            </fieldset>
            {characterError && <p className="error-message" role="alert">{characterError}</p>}
            <button className="primary-button" disabled={characterBusy} type="submit">{characterBusy ? "Creating character…" : "Create character"}</button>
          </form>
          {canEditContent && <button className="text-button" onClick={() => setStudioMode(true)} type="button">Open content studio</button>}
          <button className="text-button" onClick={signOut} type="button">Sign out</button>
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="wordmark" href="#world">PLIGHT</a>
        <div className="topbar-right">
          <button className="text-button" onClick={() => setInventoryView("all")} type="button">Inventory</button>
          <button className="text-button" onClick={openPeople} type="button">Party & friends</button>
          <button className="text-button" onClick={openOwnProfile} type="button">My profile</button>
          {canEditContent && <button className="text-button studio-nav-trigger" onClick={() => setStudioMode(true)} type="button">Content studio</button>}
          <button className="text-button" onClick={signOut} type="button">Sign out</button>
        </div>
      </header>
      {notice && <div className="notice" role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button></div>}
      <main className="world-layout" id="world">
        <section className="panel activity-panel" aria-label="Activity and command">
          <header className="panel-heading location-panel-heading">
            <h1 className="location-heading">{snapshot?.character.area_name || "Entering the world"}</h1>
          </header>
          <div
            className="activity-stream"
            onScroll={(event) => {
              const { scrollHeight, scrollTop, clientHeight } = event.currentTarget;
              followActivityRef.current = scrollHeight - scrollTop - clientHeight < 48;
            }}
            ref={activityScrollRef}
            aria-live="polite"
          >
            <div className="activity-stream-content">
              {activity.map((entry) => (
                <article className="action-result" key={entry.id || entry.request_id}>
                  {entry.type === "location" && <p className="world-text">{entry.text}</p>}
                  {(entry.result?.messages || []).map((message, messageIndex) => (
                    <p className={activityMessageClass(message, entry)} key={messageIndex}>{message}</p>
                  ))}
                  {(entry.result?.dialogues || []).map((dialogue) => {
                    const busyKey = `${entry.request_id}:${dialogue.occurrence_id}`;
                    return (
                      <section className="dialogue-interaction" key={dialogue.occurrence_id}>
                        <header><span>{dialogue.npc_name} / {dialogue.title}</span></header>
                        <div className="dialogue-history">
                          {(dialogue.history || [{ speaker: dialogue.npc_name, text: dialogue.text }]).map((line, lineIndex) => (
                            <p className={line.speaker === "You" ? "player-dialogue-line" : "npc-dialogue-line"} key={lineIndex}>
                              <strong>{line.speaker}</strong> {line.text}
                            </p>
                          ))}
                        </div>
                        {dialogue.choices.length > 0 ? (
                          <div className="dialogue-options">
                            {dialogue.choices.map((choice) => (
                              <button className="dialogue-choice-button" disabled={dialogueBusyKey === busyKey} key={choice.id} onClick={() => selectDialogueChoice(entry, dialogue, choice)} type="button">
                                {choice.text}
                              </button>
                            ))}
                          </div>
                        ) : <p className="dialogue-finished">The conversation has ended.</p>}
                      </section>
                    );
                  })}
                </article>
              ))}
            </div>
          </div>
          <form className="command-compose" onSubmit={submitCommand}>
            <label className="sr-only" htmlFor="command-input">Enter a command</label>
            <div className="command-entry">
              <span aria-hidden="true" className="prompt-mark">›</span>
              <input autoComplete="off" id="command-input" maxLength={500} onChange={(event) => setCommand(event.target.value)} placeholder="Type 'help' if help is needed" value={command} />
              <button aria-label="Submit action" className="send-button" disabled={!command.trim() || commandBusy} type="submit">{commandBusy ? "…" : "↗"}</button>
            </div>
          </form>
        </section>

        <aside className="side-column">
          <section className="panel location-content-panel" aria-label="Current location">
            <header className="panel-heading compact"><h2>{snapshot?.area?.name || "Current area"}</h2></header>
            <div className="location-content">
              <p className="location-description">{snapshot?.area?.description || "The world is loading."}</p>
              <div className="location-stat-block">
                <span>{snapshot?.character?.name}</span>
                <span>LVL {snapshot?.character?.level ?? "—"}</span>
                <span>XP {snapshot?.character?.experience_progress ?? "—"}/{snapshot?.character?.experience_to_next_level ?? "—"}</span>
                <span>HP {snapshot?.character?.stats?.health ?? "—"}/{snapshot?.character?.stats?.max_health ?? "—"}</span>
                <span>ATK {snapshot?.character?.stats?.attack ?? "—"}</span>
                <span>DEF {snapshot?.character?.stats?.defense ?? "—"}</span>
                <span>SPD {snapshot?.character?.stats?.speed ?? "—"}</span>
              </div>
              <div className="location-equipment">
                <span>LEFT: {equipmentName(snapshot, "left_hand")}</span>
                <span>RIGHT: {equipmentName(snapshot, "right_hand")}</span>
              </div>
              <WorldEntityList
                title="Exits"
                entities={snapshot?.area?.exit_details || snapshot?.area?.exits || []}
                renderItem={(exit) => {
                  const direction = typeof exit === "string" ? exit : exit.direction;
                  const destination = snapshot?.area?.exit_destinations?.[direction];
                  return (
                    <div className={`world-exit ${exit.accessible === false ? "locked" : ""}`} key={direction}>
                      <button
                        aria-label={exit.reason || `Travel ${direction}${destination ? ` to ${destination}` : ""}`}
                        onClick={() => enterCommand(`travel ${direction}`)}
                        title={exit.reason || undefined}
                        type="button"
                      >
                        {direction}{destination ? ` → ${destination}` : ""}
                        {exit.accessible === false ? " · SEALED" : ""}
                      </button>
                    </div>
                  );
                }}
              />
              <WorldEntityList title="NPCs" entities={snapshot?.area?.npcs || []} renderItem={(npc) => (
                <article className="world-entity npc-entity" key={npc.id}>
                  <strong>{npc.name}</strong><p>{npc.description}</p>
                  <button onClick={() => enterCommand(`talk to ${npc.name}`)} type="button">Talk</button>
                  {(npc.quests || []).map((quest) => (
                    <section className="quest-offer" key={quest.id}>
                      <h3>{quest.title}</h3>
                      <p>{quest.description}</p>
                      <span className={`quest-status ${quest.status}`}>{quest.status.replace("_", " ")}</span>
                      {quest.objectives.map((objective) => (
                        <p className="quest-objective" key={objective.id}>
                          {objective.type === "collect" ? "Collect" : objective.type === "kill" ? "Defeat" : objective.type === "talk" ? "Talk to" : "Visit"} {objective.target_name}: {objective.current}/{objective.required}
                        </p>
                      ))}
                      {quest.status === "available" && (
                        <button
                          className="dialogue-choice-button"
                          disabled={questBusyId === quest.id}
                          onClick={() => runQuestAction(quest, "accept")}
                          type="button"
                        >
                          {questBusyId === quest.id ? "Accepting…" : "Accept quest"}
                        </button>
                      )}
                      {quest.status === "active" && (
                        <button
                          className="dialogue-choice-button"
                          disabled={!quest.can_turn_in || questBusyId === quest.id}
                          onClick={() => runQuestAction(quest, "turn-in")}
                          type="button"
                        >
                          {questBusyId === quest.id ? "Claiming…" : "Turn in and claim rewards"}
                        </button>
                      )}
                      {quest.status === "completed" && (
                        <p className="quest-complete">
                          Completed · {quest.reward_experience} XP
                          {(quest.reward_items || []).map((reward) => ` · ${reward.quantity} ${reward.item_name}`).join("")}
                        </p>
                      )}
                    </section>
                  ))}
                </article>
              )} />
              <WorldEntityList
                title="Quest tracker"
                entities={snapshot?.quest_log || []}
                renderItem={(quest) => (
                  <article className="quest-tracker-entry" key={quest.id}>
                    <div className="quest-tracker-heading">
                      <strong>{quest.title}</strong>
                      <span className={`quest-status ${quest.status}`}>{quest.status}</span>
                    </div>
                    <p>{quest.description}</p>
                    <small>Given by {quest.giver_name}</small>
                    {quest.current_step_title && <strong className="quest-step-title">{quest.current_step_title}</strong>}
                    {quest.step_description && <p>{quest.step_description}</p>}
                    {quest.objectives.map((objective) => (
                      <p className="quest-objective" key={objective.id}>
                        {objective.type === "collect" ? "Collect" : objective.type === "kill" ? "Defeat" : objective.type === "talk" ? "Talk to" : "Visit"} {objective.target_name}: {objective.current}/{objective.required}
                      </p>
                    ))}
                    {quest.can_choose && (
                      <div className="quest-step-choices">
                        {quest.choices.map((choice) => (
                          <button
                            className="dialogue-choice-button"
                            disabled={questBusyId === quest.id}
                            key={choice.id}
                            onClick={() => runQuestAction(quest, "choose", {
                              step_id: quest.current_step_id,
                              choice_id: choice.id,
                            })}
                            type="button"
                          >
                            {choice.text}
                          </button>
                        ))}
                      </div>
                    )}
                    {quest.can_turn_in && <small>Return to {quest.giver_name} to claim your rewards.</small>}
                  </article>
                )}
              />
              <WorldEntityList title="Enemies" entities={snapshot?.area?.enemies || []} renderItem={(enemy) => (
                <article className="world-entity enemy-entity" key={enemy.id}>
                  <strong>{enemy.name}</strong>
                  <span>HP {enemy.health}/{enemy.max_health} · D{enemy.attack_die_sides} · {(enemy.behavior || "neutral").toUpperCase()}</span>
                  <p>{enemy.description}</p>
                  <button onClick={() => enterCommand(`attack ${enemy.name}`)} type="button">Attack</button>
                </article>
              )} />
              <WorldEntityList title="Objects and resources" entities={[
                ...(snapshot?.area?.objects || []),
                ...(snapshot?.area?.resources || []),
              ]} renderItem={(entity) => (
                <article className="world-entity" key={entity.id}>
                  <strong>{entity.name}</strong><p>{entity.description}</p>
                </article>
              )} />
            </div>
          </section>
          <section className="panel atmosphere-panel" aria-label="Atmosphere">
            <header className="panel-heading compact atmosphere-heading"><h2>Atmosphere</h2></header>
            <dl className="atmosphere-list">
              <div><dt>WEATHER</dt><dd>{snapshot?.atmosphere.weather || "—"}</dd></div>
              <div><dt>TIME</dt><dd>{snapshot?.atmosphere.time_of_day || "—"}</dd></div>
              <div className="atmosphere-ambience">
                <dt>AMBIENCE</dt>
                <dd className="ambience-feed" aria-live="polite">
                  {ambienceEvents.map((event) => <span className="ambience-line" key={event.id}>{event.text}</span>)}
                </dd>
              </div>
            </dl>
          </section>
          <ChatPanel
            activeChannel={activeChannel}
            channels={channels}
            messages={messages}
            onClose={closeChannel}
            onPrivateChat={openPrivateChat}
            onSelect={setActiveChannelId}
            onSend={sendChat}
          />
        </aside>
      </main>

      {inventoryView && (
        <InventoryDialog
          busy={commandBusy}
          onClose={() => setInventoryView(null)}
          onEquip={(itemId, slot) => runCommand(`equip ${itemId.replaceAll("_", " ")} in my ${slot.replaceAll("_", " ")}`)}
          onUnequip={(slot) => runCommand(`unequip from my ${slot.replaceAll("_", " ")}`)}
          onSelectView={setInventoryView}
          snapshot={snapshot}
          view={inventoryView}
        />
      )}

      {profile && (
        <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeProfile(); }}>
          <section aria-labelledby="profile-title" aria-modal="true" className="profile-dialog" role="dialog">
            <button aria-label="Close profile" className="dialog-close" onClick={closeProfile} type="button">×</button>
            <p className="eyebrow">{profile.account_id === snapshot?.account_id ? "YOUR CHARACTER PROFILE" : "TRAVELER PROFILE"}</p>
            {profile.picture_src
              ? <img alt={`${profile.name}'s profile`} className="profile-avatar-image" src={profile.picture_src} />
              : <div className="profile-avatar">{profile.name.slice(0, 1).toUpperCase()}</div>}
            <h2 id="profile-title">{profile.name}</h2>
            <p>{profile.species} · Last seen in {profile.area_name}{profile.pronouns ? ` · ${profile.pronouns}` : ""}</p>
            {profile.account_id === snapshot?.account_id ? (
              <form className="profile-edit-form" onSubmit={saveProfile}>
                <label>Pronouns<input maxLength={64} onChange={(event) => setProfileForm((current) => ({ ...current, pronouns: event.target.value }))} value={profileForm.pronouns} /></label>
                <label>Character lore<textarea maxLength={2000} onChange={(event) => setProfileForm((current) => ({ ...current, lore: event.target.value }))} rows={5} value={profileForm.lore} /></label>
                <label>Profile picture<input accept="image/png,image/jpeg,image/webp" disabled={profileBusy} onChange={(event) => { uploadProfilePicture(event.target.files?.[0]); event.target.value = ""; }} type="file" /></label>
                {profile.picture_src && <button className="text-button" disabled={profileBusy} onClick={removeProfilePicture} type="button">Remove profile picture</button>}
                {profileError && <p className="error-message" role="alert">{profileError}</p>}
                <button className="primary-button" disabled={profileBusy} type="submit">{profileBusy ? "Saving…" : "Save profile"}</button>
              </form>
            ) : (
              <>
                <p className="profile-lore">{profile.lore || "No lore has been shared yet."}</p>
                {profile.equipped_gear && (
                  <section className="profile-equipment" aria-label="Equipped gear">
                    <h3>Equipped gear</h3>
                    {Object.entries(profile.equipped_gear).map(([slot, item]) => item && (
                      <p key={slot}><strong>{EQUIPMENT_SLOT_LABELS[slot] || slot.replaceAll("_", " ")}</strong>: {item}</p>
                    ))}
                  </section>
                )}
                {(!partyState.party || partyState.party.leader_account_id === snapshot?.account_id) && (
                  <button
                    className="dialogue-choice-button"
                    disabled={partyBusy}
                    onClick={() => invitePlayerToParty(profile.account_id, profile.name)}
                    type="button"
                  >
                    {partyBusy ? "Sending…" : partyState.party ? "Invite to party" : "Create party & invite"}
                  </button>
                )}
                {profileError && <p className="error-message" role="alert">{profileError}</p>}
                <button className="primary-button" onClick={() => openPrivateChat(profile.account_id, profile.name)} type="button">Open private chat</button>
              </>
            )}
          </section>
        </div>
      )}
      {peopleOpen && (
        <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePeople(); }}>
          <section aria-labelledby="people-title" aria-modal="true" className="people-dialog" role="dialog">
            <button aria-label="Close friends" className="dialog-close" onClick={closePeople} type="button">×</button>
            <p className="eyebrow">PLAYERS</p>
            <h2 id="people-title">Players, friends & party</h2>
            <form className="player-search-form" onSubmit={searchPlayers}>
              <label htmlFor="player-search">Search character names</label>
              <div><input id="player-search" maxLength={32} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Enter part of a name" value={searchQuery} /><button className="primary-button" disabled={peopleBusy || !searchQuery.trim()} type="submit">Search</button></div>
            </form>
            {peopleError && <p className="error-message" role="alert">{peopleError}</p>}
            {peopleBusy && <p className="people-empty">Loading…</p>}
            <section className="people-section">
              <h3>{partyState.party ? "Your party" : "Party"}</h3>
              {partyState.party ? (
                <>
                  <ul className="party-member-list">
                    {partyState.party.members.map((member) => (
                      <li key={member.account_id}>
                        <span>
                          <strong>{member.name}</strong>
                          {member.is_leader ? " · Leader" : ""}
                          <small>{member.online ? "Online" : "Offline"} · {member.area_name}</small>
                        </span>
                        {partyState.party.leader_account_id === snapshot?.account_id
                          && member.account_id !== snapshot?.account_id
                          && <button
                            className="text-button"
                            disabled={partyBusy}
                            onClick={() => performPartyAction(
                              `/api/v1/party/members/${encodeURIComponent(member.account_id)}`,
                              "DELETE",
                              `Remove ${member.name} from your party?`,
                              `${member.name} left the party.`,
                            )}
                            type="button"
                          >Remove</button>}
                      </li>
                    ))}
                  </ul>
                  <div className="party-actions">
                    <button className="dialogue-choice-button" onClick={() => setActiveChannelId(partyState.party.channel_id)} type="button">Open party chat</button>
                    {partyState.party.leader_account_id === snapshot?.account_id
                      ? <>
                        <button className="text-button" disabled={partyBusy} onClick={() => performPartyAction("/api/v1/party/membership", "DELETE", "Leave your party? Leadership may transfer to another online member.", "You left the party.")} type="button">Leave party</button>
                        <button className="text-button" disabled={partyBusy} onClick={() => performPartyAction("/api/v1/party", "DELETE", "Disband the party for everyone?", "The party was disbanded.")} type="button">Disband party</button>
                      </>
                      : <button className="text-button" disabled={partyBusy} onClick={() => performPartyAction("/api/v1/party/membership", "DELETE", "Leave this party?", "You left the party.")} type="button">Leave party</button>}
                  </div>
                  {partyState.party.leader_account_id !== snapshot?.account_id && (
                    <p className="people-empty">Only the party leader can invite or remove members.</p>
                  )}
                </>
              ) : (
                <button className="primary-button" disabled={partyBusy} onClick={createParty} type="button">
                  {partyBusy ? "Creating…" : "Create party"}
                </button>
              )}
              {partyState.incoming_invitations.length > 0 && (
                <div className="party-invitations">
                  <h4>Party invitations</h4>
                  {partyState.incoming_invitations.map((invitation) => (
                    <article className="player-card" key={invitation.invite_id}>
                      <p>{invitation.player?.name || "A player"} invited you to their party.</p>
                      {partyState.party
                        ? <p className="people-empty">Leave your current party before accepting another invitation.</p>
                        : <div className="party-actions">
                          <button className="dialogue-choice-button" disabled={partyBusy} onClick={() => respondToPartyInvite(invitation, "accepted")} type="button">Accept</button>
                          <button className="text-button" disabled={partyBusy} onClick={() => respondToPartyInvite(invitation, "declined")} type="button">Decline</button>
                        </div>}
                    </article>
                  ))}
                </div>
              )}
              {partyState.outgoing_invitations.length > 0 && (
                <div className="party-invitations">
                  <h4>Pending invitations</h4>
                  {partyState.outgoing_invitations.map((invitation) => (
                    <p className="people-empty" key={invitation.invite_id}>
                      Waiting for {invitation.player?.name || "player"}.
                    </p>
                  ))}
                </div>
              )}
            </section>
            {incomingRequests.length > 0 && <section className="people-section"><h3>Friend requests</h3>
              {incomingRequests.map((request) => <article className="player-card" key={request.request_id}>
                <button className="player-name-link" onClick={() => openPlayerProfile(request.player.account_id)} type="button">{request.player.name}</button>
                <p>{[request.player.species, request.player.pronouns].filter(Boolean).join(" · ")}</p>
                <p>{request.player.lore || "No lore has been shared yet."}</p>
                <button className="dialogue-choice-button" disabled={peopleBusy} onClick={() => requestFriend({ ...request.player, friend_status: "incoming_pending" })} type="button">Accept request</button>
              </article>)}
            </section>}
            <section className="people-section"><h3>Your friends</h3>
              {friendList.length ? friendList.map((player) => <button className="player-name-link" key={player.account_id} onClick={() => openPlayerProfile(player.account_id)} type="button">{player.name} · {player.species}</button>) : <p className="people-empty">No friends yet.</p>}
            </section>
            {playerResults.length > 0 && <section className="people-section"><h3>Search results</h3>
              {playerResults.map((player) => {
                const action = friendAction(player.friend_status);
                return <article className="player-card" key={player.account_id}>
                  <div className="player-card-heading">
                    <button className="player-name-link" onClick={() => openPlayerProfile(player.account_id)} type="button">{player.name}</button>
                    {directoryPictureUrls[player.account_id] && <img alt="" className="player-thumb" src={directoryPictureUrls[player.account_id]} />}
                  </div>
                  <p>{[player.species, player.pronouns, player.area_name ? `Last seen in ${player.area_name}` : ""].filter(Boolean).join(" · ")}</p>
                  <p>{player.lore || "No lore has been shared yet."}</p>
                  <button className="dialogue-choice-button" disabled={peopleBusy || action.disabled} onClick={() => requestFriend(player)} type="button">{action.label}</button>
                </article>;
              })}
            </section>}
          </section>
        </div>
      )}
    </div>
  );
}

function equipmentName(world, slot) {
 const itemId = world?.character?.equipment?.[slot] || "fist";
 return formatEquipmentItem(itemId, world?.character?.inventory_items || []);
}

function InventoryDialog({ busy, onClose, onEquip, onUnequip, onSelectView, snapshot, view }) {
  const [selectedSlots, setSelectedSlots] = useState({});
  const items = snapshot?.character?.inventory_items || [];
  const visibleSlots = equipmentSlotsForView(view);
  const visibleItems = items.filter((item) => {
    if (view === "armor") return item.equipable_slots.some((slot) => !EQUIPMENT_SLOT_GROUPS.hands.includes(slot));
    if (view === "hands" || view === "weapons") return item.equipable_slots.some((slot) => EQUIPMENT_SLOT_GROUPS.hands.includes(slot));
    return true;
  });
  const views = [["all", "All"], ["armor", "Armor"], ["hands", "Hands"]];

  useEffect(() => setSelectedSlots({}), [view]);

  return (
    <div className="dialog-backdrop inventory-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section aria-labelledby="inventory-title" aria-modal="true" className="inventory-dialog" role="dialog">
        <button aria-label="Close inventory" className="dialog-close" onClick={onClose} type="button">×</button>
        <p className="eyebrow">CHARACTER</p>
        <h2 id="inventory-title">Inventory & equipment</h2>
        <div className="inventory-tabs" aria-label="Inventory views">
          {views.map(([id, label]) => (
            <button aria-pressed={view === id} className={view === id ? "selected" : ""} key={id} onClick={() => onSelectView(id)} type="button">{label}</button>
          ))}
        </div>
        <section className="inventory-equipment-section">
          <h3>Equipment</h3>
          <div className="equipment-grid">
            {visibleSlots.map((slot) => {
              const itemId = snapshot?.character?.equipment?.[slot] || "";
              return (
                <article className="equipment-slot" key={slot}>
                  <span>{EQUIPMENT_SLOT_LABELS[slot]}</span>
                  <strong>{formatEquipmentItem(itemId, items)}</strong>
                  {itemId && itemId !== "fist" && <button disabled={busy} onClick={() => onUnequip(slot)} type="button">Unequip</button>}
                </article>
              );
            })}
          </div>
        </section>
        <section className="inventory-items-section">
          <h3>Carrying</h3>
          {visibleItems.length ? visibleItems.map((item) => (
            <article className="inventory-item" key={item.id}>
              <div><strong>{item.name}</strong><span> × {item.quantity}</span></div>
              {itemCanEquip(item) ? (
                <div className="inventory-equip-controls">
                  <label>
                    <span className="sr-only">Equipment slot for {item.name}</span>
                    <select
                      disabled={busy}
                      onChange={(event) => setSelectedSlots((current) => ({ ...current, [item.id]: event.target.value }))}
                      value={selectedSlots[item.id] || item.equipable_slots[0]}
                    >
                      {item.equipable_slots.map((slot) => <option key={slot} value={slot}>{EQUIPMENT_SLOT_LABELS[slot]}</option>)}
                    </select>
                  </label>
                  <button disabled={busy} onClick={() => onEquip(item.id, selectedSlots[item.id] || item.equipable_slots[0])} type="button">Equip</button>
                </div>
              ) : <p className="item-not-equipable">This item type has no equipment definition.</p>}
            </article>
          )) : <p className="inventory-empty">Nothing is carried in this view.</p>}
        </section>
      </section>
    </div>
  );
}

function WorldEntityList({ title, entities, renderItem }) {
  return (
    <section className="world-entity-group">
      <h3>{title}</h3>
      {entities.length ? entities.map(renderItem) : <p className="world-empty">None</p>}
    </section>
  );
}
