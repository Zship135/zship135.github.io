import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiBlob, liveUrl } from "./api.js";
import ContentStudio from "./ContentStudio.jsx";
import Dice3D, { DiePreview } from "./Dice3D.jsx";
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
  if (/^(You gain \d+ experience\.|Loot:|Currency:|Reward:|No items dropped\.)/i.test(message)) return "reward-text";
  if (/^(Roll for initiative:|Roll for initiative against|You roll a D20:)/i.test(message)) return "initiative-text";
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
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [audioVolume, setAudioVolume] = useState(0.65);
  const [audioError, setAudioError] = useState("");
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
  const [pendingRollRequestId, setPendingRollRequestId] = useState(null);
  const [rollBusy, setRollBusy] = useState(false);
  const [rollAnimation, setRollAnimation] = useState(null);
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
  const musicAudioRef = useRef(null);
  const actionAudioRef = useRef(null);
  const audioUrlsRef = useRef(new Map());
  const audioLoadsRef = useRef(new Map());
  const audioEnabledRef = useRef(false);
  const audioVolumeRef = useRef(0.65);
  const actionSoundQueueRef = useRef(Promise.resolve());

  const getAudioSource = useCallback(async (assetId) => {
    const cached = audioUrlsRef.current.get(assetId);
    if (cached) {
      audioUrlsRef.current.delete(assetId);
      audioUrlsRef.current.set(assetId, cached);
      return cached;
    }
    const pending = audioLoadsRef.current.get(assetId);
    if (pending) return pending;
    const loadPromise = (async () => {
      const blob = await apiBlob(`/api/v1/content/audio/${encodeURIComponent(assetId)}`, { token });
      const objectUrl = URL.createObjectURL(blob);
      audioUrlsRef.current.set(assetId, objectUrl);
      while (audioUrlsRef.current.size > 12) {
        const activeSources = new Set([
          musicAudioRef.current?.src,
          actionAudioRef.current?.src,
        ]);
        const staleEntry = [...audioUrlsRef.current].find(
          ([cachedId, source]) => cachedId !== assetId && !activeSources.has(source),
        );
        if (!staleEntry) break;
        URL.revokeObjectURL(staleEntry[1]);
        audioUrlsRef.current.delete(staleEntry[0]);
      }
      return objectUrl;
    })();
    audioLoadsRef.current.set(assetId, loadPromise);
    try {
      return await loadPromise;
    } finally {
      if (audioLoadsRef.current.get(assetId) === loadPromise) {
        audioLoadsRef.current.delete(assetId);
      }
    }
  }, [token]);

  useEffect(() => {
    const player = musicAudioRef.current;
    const assetId = snapshot?.area?.music_asset_id;
    if (!player) return undefined;
    if (!audioEnabled || !assetId) {
      player.pause();
      if (!assetId) player.removeAttribute("src");
      return undefined;
    }
    let cancelled = false;
    player.pause();
    getAudioSource(assetId)
      .then((source) => {
        if (cancelled || !audioEnabledRef.current) return;
        player.src = source;
        player.loop = true;
        player.volume = audioVolumeRef.current;
        return player.play();
      })
      .catch((error) => {
        if (!cancelled) setAudioError(`Location music could not play: ${error.message}`);
      });
    return () => { cancelled = true; };
  }, [audioEnabled, getAudioSource, snapshot?.area?.music_asset_id, studioMode]);

  useEffect(() => {
    audioEnabledRef.current = audioEnabled;
    if (!audioEnabled) {
      musicAudioRef.current?.pause();
      actionAudioRef.current?.pause();
    }
  }, [audioEnabled]);

  useEffect(() => {
    audioVolumeRef.current = audioVolume;
    if (musicAudioRef.current) musicAudioRef.current.volume = audioVolume;
    if (actionAudioRef.current) actionAudioRef.current.volume = audioVolume;
  }, [audioVolume]);

  useEffect(() => () => {
    musicAudioRef.current?.pause();
    actionAudioRef.current?.pause();
    for (const source of audioUrlsRef.current.values()) URL.revokeObjectURL(source);
    audioUrlsRef.current.clear();
  }, []);

  useEffect(() => {
    if (!rollAnimation || rollAnimation.rolling) return undefined;
    const timer = window.setTimeout(() => setRollAnimation(null), 3600);
    return () => window.clearTimeout(timer);
  }, [rollAnimation]);

  const queueActionSounds = useCallback((actionIds, soundAssignments) => {
    if (!Array.isArray(actionIds) || actionIds.length === 0) return;
    const playSounds = async () => {
      for (const actionId of actionIds) {
        if (!audioEnabledRef.current) return;
        const isAttack = ["attack", "light_attack", "heavy_attack"].includes(actionId);
        const assetId = soundAssignments?.[actionId];
        if (!isAttack && !assetId) continue;
        const source = isAttack ? "/audio/fight.mp3" : await getAudioSource(assetId);
        if (!audioEnabledRef.current) return;
        const player = new Audio(source);
        player.volume = audioVolumeRef.current;
        actionAudioRef.current = player;
        await new Promise((resolve, reject) => {
          player.addEventListener("ended", resolve, { once: true });
          player.addEventListener("pause", resolve, { once: true });
          player.addEventListener("error", () => reject(new Error("An action sound could not be played.")), { once: true });
          player.play().catch(reject);
        });
      }
    };
    actionSoundQueueRef.current = actionSoundQueueRef.current
      .then(playSounds, playSounds)
      .catch((error) => setAudioError(`Action sound could not play: ${error.message}`));
  }, [getAudioSource]);
  const playRollSound = useCallback(() => {
    const play = async () => {
      if (!audioEnabledRef.current) return;
      const player = new Audio("/audio/dice.mp3");
      player.volume = audioVolumeRef.current;
      actionAudioRef.current = player;
      await new Promise((resolve, reject) => {
        player.addEventListener("ended", resolve, { once: true });
        player.addEventListener("pause", resolve, { once: true });
        player.addEventListener("error", () => reject(new Error("The dice sound could not be played.")), { once: true });
        player.play().catch(reject);
      });
    };
    actionSoundQueueRef.current = actionSoundQueueRef.current
      .then(play, play)
      .catch((error) => setAudioError(error.message));
  }, []);
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
  const [mapOpen, setMapOpen] = useState(false);
  const [diceOpen, setDiceOpen] = useState(false);
  const [diceBusy, setDiceBusy] = useState(false);
  const [diceError, setDiceError] = useState("");
  const [notice, setNotice] = useState("");
  const commandInputRef = useRef(null);
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
        if (result.status === "awaiting_roll") {
          setPendingRollRequestId(item.request_id);
          break;
        }
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
    if (!text || commandBusy || pendingRollRequestId) return;
    if (snapshot?.character?.has_map && /^(?:open|view|check|show|unfold|look at|read)\s+(?:the\s+|my\s+)?(?:world\s+)?map$/i.test(text)) {
      setCommand("");
      setMapOpen(true);
      return;
    }
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
      if (result.status === "awaiting_roll") {
        setPendingRollRequestId(result.request_id);
      } else if (result.status !== "queued") {
        removePendingCommand(accountId, request.request_id);
      }
      queueActionSounds(
        result.result?.action_events,
        result.result?.snapshot?.action_sounds || snapshot?.action_sounds,
      );
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

  async function selectDieSkin(skinId) {
    setDiceBusy(true);
    setDiceError("");
    try {
      setSnapshot(await api("/api/v1/character/die-skin", { token, method: "PUT", body: JSON.stringify({ skin_id: skinId }) }));
    } catch (error) {
      setDiceError(error.message);
    } finally {
      setDiceBusy(false);
    }
  }

  async function rollD20() {
    if (commandBusy || rollBusy) return;
    setRollBusy(true);
    setRollAnimation({ rolling: true, rolls: [] });
    playRollSound();
    try {
      const body = { roll_id: crypto.randomUUID() };
      if (pendingRollRequestId) body.request_id = pendingRollRequestId;
      const result = await api("/api/v1/roll", {
        token,
        method: "POST",
        body: JSON.stringify(body),
      });
      const requestId = pendingRollRequestId;
      if (requestId && result.status !== "awaiting_roll") {
        removePendingCommand(accountId, requestId);
        setPendingRollRequestId(null);
      }
      setActivity((current) => upsertActivity(current, result));
      if (result.result?.roll_animation) setRollAnimation(result.result.roll_animation);
      queueActionSounds(
        result.result?.action_events,
        result.result?.snapshot?.action_sounds || snapshot?.action_sounds,
      );
      await refreshWorld(token);
    } catch (error) {
      setRollAnimation(null);
      showError(error);
    } finally {
      setRollBusy(false);
    }
  }

  async function submitCommand(event) {
    event.preventDefault();
    await runCommand(command);
    requestAnimationFrame(() => {
      const input = commandInputRef.current;
      if (input && !input.disabled) input.focus();
    });
  }

  function enterCommand(text) {
    setCommand(text);
    commandInputRef.current?.focus();
  }

  function toggleAudio() {
    const enabled = !audioEnabledRef.current;
    audioEnabledRef.current = enabled;
    setAudioEnabled(enabled);
    setAudioError("");
    if (!enabled) {
      musicAudioRef.current?.pause();
      actionAudioRef.current?.pause();
    }
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
      queueActionSounds(["talk"], snapshot?.action_sounds);
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

  async function buyFromShop(entry, dialogue, offer, mode = "buy") {
    const busyKey = `${entry.request_id}:${dialogue.occurrence_id}`;
    setDialogueBusyKey(busyKey);
    setNotice("");
    try {
      const result = await api(`/api/v1/shop/${mode}`, {
        token,
        method: "POST",
        body: JSON.stringify({ npc_id: dialogue.npc_id, item_id: offer.item_id, quantity: 1 }),
      });
      queueActionSounds([mode === "sell" ? "shop_sell" : "shop_buy"], snapshot?.action_sounds);
      setSnapshot(result.snapshot);
      setActivity((current) => current.map((currentEntry) => {
        if (currentEntry.request_id !== entry.request_id) return currentEntry;
        const dialogues = (currentEntry.result?.dialogues || []).map((currentDialogue) => (
          currentDialogue.occurrence_id === dialogue.occurrence_id
            ? { ...currentDialogue, ...result.shop, occurrence_id: currentDialogue.occurrence_id, notice: result.messages.join(" ") }
            : currentDialogue
        ));
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
      <>
        <audio aria-hidden="true" ref={musicAudioRef} />
        <ContentStudio
          onClose={() => {
            setStudioMode(false);
            refreshWorld(token).catch(showError);
          }}
          onSignOut={signOut}
          token={token}
        />
      </>
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
      <audio aria-hidden="true" ref={musicAudioRef} />
      <header className="topbar">
        <a className="wordmark" href="#world">PLIGHT</a>
        <div className="topbar-right">
          <button className="text-button" onClick={() => setInventoryView("all")} type="button">Inventory</button>
          {(snapshot?.character?.die_skins?.unlocked || []).length > 0 && <button className="text-button" onClick={() => setDiceOpen(true)} type="button">Dice</button>}
          {snapshot?.character?.has_map && <button className="text-button" onClick={() => setMapOpen(true)} type="button">Map</button>}
          <button className="text-button" onClick={openPeople} type="button">Party & friends</button>
          <button className="text-button" onClick={openOwnProfile} type="button">My profile</button>
          {canEditContent && <button className="text-button studio-nav-trigger" onClick={() => setStudioMode(true)} type="button">Content studio</button>}
          <div className="audio-controls">
            <button aria-pressed={audioEnabled} className="text-button" onClick={toggleAudio} type="button">
              {audioEnabled ? "Sound on" : "Sound off"}
            </button>
            <label className="sr-only" htmlFor="audio-volume">Game audio volume</label>
            <input
              aria-label="Game audio volume"
              id="audio-volume"
              max="1"
              min="0"
              onChange={(event) => setAudioVolume(Number(event.target.value))}
              step="0.05"
              type="range"
              value={audioVolume}
            />
          </div>
          <button className="text-button" onClick={signOut} type="button">Sign out</button>
        </div>
      </header>
      {audioError && <div className="audio-error" role="status">{audioError}<button aria-label="Dismiss audio message" onClick={() => setAudioError("")} type="button">×</button></div>}
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
                <article className="action-result" key={entry.id || entry.request_id || entry.roll_id}>
                  {entry.type === "location" && <p className="world-text">{entry.text}</p>}
                  {(entry.result?.messages || []).map((message, messageIndex) => (
                    <p className={activityMessageClass(message, entry)} key={messageIndex}>{message}</p>
                  ))}
                  {(entry.result?.dialogues || []).map((dialogue) => {
                    const busyKey = `${entry.request_id}:${dialogue.occurrence_id}`;
                    if (dialogue.kind === "book") {
                      return <BookWindow dialogue={dialogue} key={dialogue.occurrence_id} />;
                    }
                    if (dialogue.kind === "shop") {
                      return (
                        <section className="dialogue-interaction shop-window" key={dialogue.occurrence_id}>
                          <header><span>{dialogue.npc_name} / Shop</span></header>
                          <div className="dialogue-history">
                            <p className="npc-dialogue-line"><strong>{dialogue.npc_name}</strong> {dialogue.text}</p>
                            {dialogue.notice && <p className="player-dialogue-line"><strong>You</strong> {dialogue.notice}</p>}
                          </div>
                          <div className="shop-wallet">
                            {(dialogue.wallet || []).map((currency) => (
                              <span className="wallet-balance" key={currency.currency_id}>
                                {currency.symbol ? `${currency.symbol}${currency.amount.toLocaleString()}` : `${currency.amount.toLocaleString()} ${currency.name}`}
                              </span>
                            ))}
                          </div>
                          <div className="dialogue-options">
                            {(dialogue.offers || []).map((offer) => (
                              <button
                                className="dialogue-choice-button shop-offer-button"
                                disabled={offer.remaining <= 0 || dialogueBusyKey === busyKey}
                                key={offer.item_id}
                                onClick={() => buyFromShop(entry, dialogue, offer)}
                                type="button"
                              >
                                <span>{offer.item_name}</span>
                                <span>{offer.price_text} · {offer.remaining > 0 ? `${offer.remaining} left` : `sold out${offer.restock_seconds_remaining ? `, restocks in ${offer.restock_seconds_remaining}s` : ""}`}</span>
                              </button>
                            ))}
                            {(dialogue.offers || []).length === 0 && (dialogue.sell_offers || []).length === 0 && <p className="dialogue-finished">Nothing is for sale right now. Stock entries need a currency set in Content Studio.</p>}
                          </div>
                          {(dialogue.sell_offers || []).length > 0 && (
                            <>
                              <p className="shop-section-label">Sell to {dialogue.npc_name}</p>
                              <div className="dialogue-options">
                                {dialogue.sell_offers.map((offer) => (
                                  <button
                                    className="dialogue-choice-button shop-offer-button"
                                    disabled={offer.remaining <= 0 || dialogueBusyKey === busyKey}
                                    key={`sell-${offer.item_id}`}
                                    onClick={() => buyFromShop(entry, dialogue, offer, "sell")}
                                    type="button"
                                  >
                                    <span>{offer.item_name} (you have {offer.owned})</span>
                                    <span>{offer.price_text} each · {offer.remaining > 0 ? `buys ${offer.remaining} more` : `not buying more${offer.restock_seconds_remaining ? `, resets in ${offer.restock_seconds_remaining}s` : ""}`}</span>
                                  </button>
                                ))}
                              </div>
                            </>
                          )}
                        </section>
                      );
                    }
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
          {rollAnimation && (
            <div aria-live="assertive" className="dice-roll-popup" role="status">
              <span className="sr-only">
                {rollAnimation.rolling ? "Rolling D20" : rollAnimation.rolls.map((roll) => `${roll.label}: ${roll.value}`).join(", ")}
              </span>
              {Array.from({ length: Math.max(1, rollAnimation.rolls.length) }, (_, index) => (
                <Dice3D
                  key={index}
                  label={rollAnimation.rolls[index]?.label}
                  skin={(snapshot?.character?.die_skins?.unlocked || []).find((skin) => skin.id === snapshot.character.die_skins.active_id)}
                  value={rollAnimation.rolls[index]?.value ?? null}
                />
              ))}
            </div>
          )}
          <form className="command-compose" onSubmit={submitCommand}>
            <label className="sr-only" htmlFor="command-input">Enter a command</label>
            {pendingRollRequestId && <p className="initiative-prompt">Roll for initiative to resolve your attack.</p>}
            <div className="command-entry">
              <span aria-hidden="true" className="prompt-mark">›</span>
              <input autoComplete="off" disabled={Boolean(pendingRollRequestId) || commandBusy} id="command-input" maxLength={500} onChange={(event) => setCommand(event.target.value)} placeholder="Type 'help' if help is needed" ref={commandInputRef} value={command} />
              <button aria-label="Roll D20" className="roll-button" disabled={commandBusy || rollBusy} onClick={rollD20} type="button">{rollBusy ? "…" : "Roll"}</button>
              <button aria-label="Submit action" className="send-button" disabled={!command.trim() || commandBusy || Boolean(pendingRollRequestId)} type="submit">{commandBusy ? "…" : "↗"}</button>
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
                {(snapshot?.character?.wallet || []).map((currency) => (
                  <span className="wallet-balance" key={currency.currency_id} title={currency.name}>
                    {currency.symbol ? `${currency.symbol}${currency.amount.toLocaleString()}` : `${currency.amount.toLocaleString()} ${currency.name}`}
                  </span>
                ))}
              </div>
              <TimedActivityPanel
                busy={commandBusy}
                character={snapshot?.character}
                onCancel={() => runCommand("stop")}
              />
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
                    <div className={`world-exit ${exit.accessible === false ? "locked" : ""} ${exit.on_quest_path ? "quest-path" : ""}`} key={direction}>
                      <button
                        aria-label={exit.reason || `Travel ${direction}${destination ? ` to ${destination}` : ""}`}
                        onClick={() => enterCommand(`travel ${direction}`)}
                        title={exit.reason || undefined}
                        type="button"
                      >
                        {direction}{destination ? ` → ${destination}` : ""}
                        {exit.accessible === false ? " · SEALED" : ""}
                        {exit.on_quest_path ? " · ★ quest" : ""}
                      </button>
                    </div>
                  );
                }}
              />
              <WorldEntityList title="NPCs" entities={snapshot?.area?.npcs || []} renderItem={(npc) => (
                <article className="world-entity npc-entity" key={npc.id}>
                  <strong>{npc.name}</strong><p>{npc.description}</p>
                  <button onClick={() => enterCommand(`talk to ${npc.name}`)} type="button">Talk</button>
                  {npc.has_shop && <button onClick={() => runCommand(`buy from ${npc.name}`)} type="button">Shop</button>}
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
                          {(quest.reward_currencies || []).map((reward) => {
                            const currency = (snapshot?.character?.wallet || []).find((entry) => entry.currency_id === reward.currency_id);
                            return ` · ${currency?.symbol ? `${currency.symbol}${reward.amount}` : `${reward.amount} ${currency?.name || reward.currency_id}`}`;
                          }).join("")}
                          {(quest.reward_die_skin_ids || []).map((id) => ` · ${snapshot?.die_skin_names?.[id] || id} die skin`).join("")}
                        </p>
                      )}
                    </section>
                  ))}
                </article>
              )} />
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
                  {entity.type === "resource" && (
                    <ResourceGatherControl
                      busy={commandBusy}
                      gathering={Boolean(snapshot?.character?.gathering)}
                      onGather={() => enterCommand(`gather ${entity.name}`)}
                      status={entity.gather_status}
                    />
                  )}
                  {entity.interaction_effect && (
                    <button
                      onClick={() => enterCommand(
                        entity.interaction_effect === "restore_health"
                          ? `rest at ${entity.name}`
                          : `set my spawn at ${entity.name}`,
                      )}
                      type="button"
                    >
                      {entity.interaction_effect === "restore_health"
                        ? "Rest and restore health"
                        : "Set respawn point here"}
                    </button>
                  )}
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
        </aside>
        <div className="lower-panels">
          <section className="panel quest-tracker-panel" aria-label="Quest tracker">
            <header className="panel-heading compact"><h2>Quest tracker</h2></header>
            <div className="location-content">
          <QuestTrackerSections
            busyId={questBusyId}
            onAction={runQuestAction}
            quests={snapshot?.quest_log || []}
            trackedId={snapshot?.tracked_quest_id || null}
          />
            </div>
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
        </div>
      </main>

      {diceOpen && (
        <DiceSkinDialog
          busy={diceBusy}
          dieSkins={snapshot?.character?.die_skins}
          error={diceError}
          onClose={() => setDiceOpen(false)}
          onSelect={selectDieSkin}
        />
      )}

      {mapOpen && snapshot?.world_map && (
        <WorldMapDialog onClose={() => setMapOpen(false)} questPath={snapshot.quest_path} worldMap={snapshot.world_map} />
      )}

      {inventoryView && (
        <InventoryDialog
          busy={commandBusy}
          onClose={() => setInventoryView(null)}
          onEquip={(itemId, slot) => runCommand(`equip ${itemId.replaceAll("_", " ")} in my ${slot.replaceAll("_", " ")}`)}
          onUnequip={(slot) => runCommand(`unequip from my ${slot.replaceAll("_", " ")}`)}
          onUse={(itemId) => runCommand(`use ${itemId.replaceAll("_", " ")}`)}
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

function TimedActivityPanel({ busy, character, onCancel }) {
  const [now, setNow] = useState(Date.now() / 1000);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!character) return null;
  const gathering = character.gathering;
  const activeEffects = (character.active_effects || []).filter(
    (effect) => Number(effect.expires_at) > now,
  );
  const skills = character.skills || [];
  const remaining = gathering
    ? Math.max(0, Math.ceil(Number(gathering.completes_at) - now))
    : 0;
  const progress = gathering?.duration_seconds
    ? Math.min(100, Math.max(
      0,
      ((now - Number(gathering.started_at)) / Number(gathering.duration_seconds)) * 100,
    ))
    : 0;

  return (
    <div className="timed-activity-panel">
      {gathering && (
        <section className="gathering-progress" aria-live="polite">
          <div>
            <strong>Gathering {gathering.resource_name}</strong>
            <span>{remaining > 0 ? `${remaining}s remaining` : "Finishing…"}</span>
          </div>
          <progress max="100" value={progress} />
          <button disabled={busy} onClick={onCancel} type="button">Stop gathering</button>
        </section>
      )}
      {skills.length > 0 && (
        <details className="character-skills">
          <summary>Proficiencies</summary>
          <div className="character-skill-list">
            {skills.map((skill) => (
              <div key={skill.id}>
                <span>{skill.name} · Lv {skill.level}</span>
                <span>{skill.experience}/{skill.experience_to_next_level} XP</span>
                <progress max={skill.experience_to_next_level} value={skill.experience} />
              </div>
            ))}
          </div>
        </details>
      )}
      {activeEffects.length > 0 && (
        <div className="active-effect-list" aria-label="Active effects">
          {activeEffects.map((effect, index) => {
            const label = effect.type === "stat_buff"
              ? `${effect.stat} ${effect.mode === "percent" ? "+" : "+"}${effect.amount}${effect.mode === "percent" ? "%" : ""}`
              : effect.type === "shield"
                ? effect.mode === "temporary_health"
                  ? `Temporary health +${effect.remaining ?? effect.amount}`
                  : `${effect.mode.replaceAll("_", " ")} shield${effect.mode === "damage_pool" ? ` (${effect.remaining ?? effect.amount} remaining)` : ""}`
                : effect.type === "luck"
                  ? "Luck"
                  : effect.type;
            const effectRemaining = Math.max(0, Math.ceil(Number(effect.expires_at) - now));
            return <span key={`${effect.type}-${effect.stat || effect.mode || index}`}>{label} · {effectRemaining}s</span>;
          })}
        </div>
      )}
    </div>
  );
}

function ResourceGatherControl({ busy, gathering, onGather, status }) {
  const [now, setNow] = useState(Date.now() / 1000);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!status?.configured) {
    return <div className="resource-gather-status"><span>Not configured for gathering.</span></div>;
  }
  const respawnRemaining = status.respawn_at
    ? Math.max(0, Math.ceil(Number(status.respawn_at) - now))
    : status.respawn_seconds_remaining;
  const available = status.available || (Boolean(status.respawn_at) && respawnRemaining === 0);

  return (
    <div className="resource-gather-status">
      {respawnRemaining > 0 ? (
        <span>Depleted · respawns in {respawnRemaining}s</span>
      ) : (
        <span>
          {status.skill_name || status.skill} level {status.skill_level}
          {status.tool_stat ? ` · ${status.minimum_tool_power}+ ${status.tool_stat} tool` : ""}
        </span>
      )}
      <button disabled={busy || gathering || !available} onClick={onGather} type="button">Gather</button>
    </div>
  );
}

function equipmentName(world, slot) {
 const itemId = world?.character?.equipment?.[slot] || (slot === "right_hand" ? "fist" : "");
 return itemId
   ? formatEquipmentItem(itemId, world?.character?.inventory_items || [])
   : "Empty";
}

function BookWindow({ dialogue }) {
  const [page, setPage] = useState(0);
  const pages = dialogue.pages || [];
  const current = pages[page];
  return (
    <section className="dialogue-interaction book-window">
      <header><span>{dialogue.title} / Page {page + 1} of {pages.length}</span></header>
      <div className="dialogue-history book-page">
        {current?.title && <h3>{current.title}</h3>}
        {(current?.text || "").split(/\n{2,}/).map((paragraph, index) => (
          <p className="book-text" key={index}>{paragraph}</p>
        ))}
      </div>
      <div className="dialogue-options book-controls">
        <button className="dialogue-choice-button" disabled={page === 0} onClick={() => setPage(page - 1)} type="button">← Previous page</button>
        <button className="dialogue-choice-button" disabled={page >= pages.length - 1} onClick={() => setPage(page + 1)} type="button">Next page →</button>
      </div>
    </section>
  );
}

function DiceSkinDialog({ busy, dieSkins, error, onClose, onSelect }) {
  const unlocked = dieSkins?.unlocked || [];
  const active = unlocked.find((skin) => skin.id === dieSkins?.active_id) || null;
  return (
    <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section aria-labelledby="dice-title" aria-modal="true" className="inventory-dialog" role="dialog">
        <button aria-label="Close dice skins" className="dialog-close" onClick={onClose} type="button">×</button>
        <p className="eyebrow">CHARACTER</p>
        <h2 id="dice-title">Dice skins</h2>
        {error && <p className="studio-message error-message" role="alert">{error}</p>}
        <div className="dice-roll-preview"><DiePreview key={active?.id || "default"} skin={active} /></div>
        <div className="die-skin-picker">
          <button className={`die-skin-option${active ? "" : " selected"}`} disabled={busy} onClick={() => onSelect(null)} type="button">
            <strong>Default die</strong>
          </button>
          {unlocked.map((skin) => (
            <button className={`die-skin-option${active?.id === skin.id ? " selected" : ""}`} disabled={busy} key={skin.id} onClick={() => onSelect(skin.id)} type="button">
              <span><strong>{skin.name}</strong>{skin.description ? <small> — {skin.description}</small> : null}</span>
              <span className="die-skin-swatches">
                {[skin.face_color, skin.edge_color, skin.number_color].map((color, index) => <i key={index} style={{ background: color }} />)}
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function WorldMapDialog({ onClose, questPath, worldMap }) {
  const locations = worldMap.locations;
  const byId = Object.fromEntries(locations.map((location) => [location.id, location]));
  const routeIds = questPath?.route || [];
  const routeEdges = new Set(routeIds.slice(1).map((id, index) => `${routeIds[index]}>${id}`));
  const xs = locations.map((location) => location.x);
  const ys = locations.map((location) => location.y);
  const minX = Math.min(...xs) - 10;
  const minY = Math.min(...ys) - 10;
  const width = Math.max(40, Math.max(...xs) - minX + 10);
  const height = Math.max(40, Math.max(...ys) - minY + 10);
  const edges = locations.flatMap((location) => Object.values(location.exits)
    .filter((destination) => byId[destination])
    .map((destination) => ({ from: location, to: byId[destination] })));
  return (
    <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section aria-labelledby="world-map-title" aria-modal="true" className="inventory-dialog world-map-dialog" role="dialog">
        <button aria-label="Close map" className="dialog-close" onClick={onClose} type="button">×</button>
        <p className="eyebrow">MAP</p>
        <h2 id="world-map-title">World map</h2>
        {questPath && (
          <p className="world-map-quest">
            ★ {questPath.quest_title}: {questPath.label}
            {routeIds.length > 1 ? ` (${routeIds.length - 1} step${routeIds.length === 2 ? "" : "s"} away)` : ""}
          </p>
        )}
        <svg className="world-map-svg" role="img" aria-label="Known locations" viewBox={`${minX} ${minY} ${width} ${height}`}>
          {edges.map(({ from, to }) => {
            const onRoute = routeEdges.has(`${from.id}>${to.id}`) || routeEdges.has(`${to.id}>${from.id}`);
            return (
              <line className={onRoute ? "map-edge route" : "map-edge"} key={`${from.id}-${to.id}`} x1={from.x} x2={to.x} y1={from.y} y2={to.y} />
            );
          })}
          {locations.map((location) => {
            const classes = [
              "map-node",
              location.visited ? "visited" : "unvisited",
              location.id === worldMap.current_id ? "current" : "",
              routeIds.includes(location.id) ? "route" : "",
              questPath?.destination_ids?.includes(location.id) ? "destination" : "",
            ].join(" ");
            return (
              <g className={classes} key={location.id}>
                <circle cx={location.x} cy={location.y} r="2.4" />
                <text x={location.x} y={location.y + 6}>{location.name}</text>
              </g>
            );
          })}
        </svg>
        <p className="studio-hint">Dim locations are adjacent areas you have not visited yet. Gold marks your current location.</p>
      </section>
    </div>
  );
}

const BODY_SLOTS = [
  ["helm", "top: 2%; left: 50%"],
  ["tunic", "top: 28%; left: 50%"],
  ["sleeves", "top: 28%; left: 11%"],
  ["gloves", "top: 28%; left: 89%"],
  ["right_hand", "top: 52%; left: 9%"],
  ["left_hand", "top: 52%; left: 91%"],
  ["pants", "top: 56%; left: 50%"],
  ["boots", "top: 86%; left: 50%"],
];
const RING_SLOTS = ["ring_1", "ring_2", "ring_3", "ring_4", "ring_5"];
const NECKLACE_SLOTS = ["necklace_1", "necklace_2"];

function ItemStats({ item }) {
  const stats = Object.entries(item.stats || {});
  return (
    <>
      {item.description ? <p className="item-description">{item.description}</p> : null}
      {stats.length ? <p className="item-stats">{stats.map(([key, value]) => `${key} ${value > 0 ? "+" : ""}${value}`).join(" · ")}</p> : null}
    </>
  );
}

function InventoryDialog({ busy, onClose, onEquip, onUnequip, onUse, onSelectView, snapshot, view }) {
  const [selectedSlots, setSelectedSlots] = useState({});
  const [activeSlot, setActiveSlot] = useState(null);
  const items = snapshot?.character?.inventory_items || [];
  const equipment = snapshot?.character?.equipment || {};
  const tab = view === "all" ? "inventory" : "equipment";

  const slotButton = (slot, style) => {
    const itemId = equipment[slot] || "";
    return (
      <button
        aria-pressed={activeSlot === slot}
        className={`body-slot${itemId ? " filled" : ""}${activeSlot === slot ? " selected" : ""}`}
        key={slot}
        onClick={() => setActiveSlot(activeSlot === slot ? null : slot)}
        style={style}
        type="button"
      >
        <span>{EQUIPMENT_SLOT_LABELS[slot]}</span>
        <strong>{formatEquipmentItem(itemId, items)}</strong>
      </button>
    );
  };
  const cssStyle = (text) => Object.fromEntries(text.split(";").map((part) => {
    const [key, value] = part.split(":").map((piece) => piece.trim());
    return [key, value];
  }));
  const activeItemId = activeSlot ? equipment[activeSlot] || "" : "";
  const activeItem = items.find((item) => item.id === activeItemId);
  const candidates = activeSlot ? items.filter((item) => item.equipable_slots.includes(activeSlot) && item.id !== activeItemId) : [];

  return (
    <div className="dialog-backdrop inventory-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section aria-labelledby="inventory-title" aria-modal="true" className="inventory-dialog" role="dialog">
        <button aria-label="Close inventory" className="dialog-close" onClick={onClose} type="button">×</button>
        <p className="eyebrow">CHARACTER</p>
        <h2 id="inventory-title">{tab === "inventory" ? "Inventory" : "Equipment"}</h2>
        <div className="inventory-tabs" aria-label="Inventory views">
          <button aria-pressed={tab === "inventory"} className={tab === "inventory" ? "selected" : ""} onClick={() => onSelectView("all")} type="button">Inventory</button>
          <button aria-pressed={tab === "equipment"} className={tab === "equipment" ? "selected" : ""} onClick={() => onSelectView("armor")} type="button">Equipment</button>
        </div>
        {tab === "inventory" ? (
          <section className="inventory-items-section">
            {items.length ? items.map((item) => (
              <article className="inventory-item" key={item.id}>
                <div className="inventory-item-main">
                  <div><strong>{item.name}</strong><span> × {item.quantity}</span></div>
                  <ItemStats item={item} />
                </div>
                <div className="inventory-item-actions">
                  {item.can_use && <button disabled={busy} onClick={() => onUse(item.id)} type="button">Use</button>}
                  {itemCanEquip(item) && (
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
                  )}
                </div>
              </article>
            )) : <p className="inventory-empty">You are carrying nothing.</p>}
          </section>
        ) : (
          <section className="equipment-section">
            <div className="equipment-paperdoll">
              <div className="equipment-side" aria-label="Rings">
                <h3>Rings</h3>
                {RING_SLOTS.map((slot) => slotButton(slot))}
              </div>
              <div className="equipment-body">
                <svg aria-hidden="true" viewBox="0 0 100 200" preserveAspectRatio="xMidYMid meet">
                  <g fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round">
                    <circle cx="50" cy="18" r="12" />
                    <path d="M44 30 v6 M56 30 v6" />
                    <path d="M30 40 Q50 34 70 40 L78 92 L68 94 L63 62 L62 112 L66 190 L53 190 L50 120 L47 190 L34 190 L38 112 L37 62 L32 94 L22 92 Z" />
                  </g>
                </svg>
                {BODY_SLOTS.map(([slot, position]) => slotButton(slot, cssStyle(position)))}
              </div>
              <div className="equipment-side" aria-label="Necklaces">
                <h3>Necklaces</h3>
                {NECKLACE_SLOTS.map((slot) => slotButton(slot))}
              </div>
            </div>
            {activeSlot ? (
              <div className="equipment-picker">
                <h3>{EQUIPMENT_SLOT_LABELS[activeSlot]}</h3>
                {activeItemId && activeItemId !== "fist" ? (
                  <article className="inventory-item">
                    <div className="inventory-item-main">
                      <div><strong>{activeItem?.name || formatEquipmentItem(activeItemId, items)}</strong><span> — equipped</span></div>
                      {activeItem ? <ItemStats item={activeItem} /> : null}
                    </div>
                    <button disabled={busy} onClick={() => onUnequip(activeSlot)} type="button">Unequip</button>
                  </article>
                ) : null}
                {candidates.length ? candidates.map((item) => (
                  <article className="inventory-item" key={item.id}>
                    <div className="inventory-item-main">
                      <div><strong>{item.name}</strong><span> × {item.quantity}</span></div>
                      <ItemStats item={item} />
                    </div>
                    <button disabled={busy} onClick={() => onEquip(item.id, activeSlot)} type="button">Equip</button>
                  </article>
                )) : <p className="inventory-empty">Nothing in your pack fits this slot.</p>}
              </div>
            ) : <p className="inventory-empty">Select a slot to equip or remove an item.</p>}
          </section>
        )}
      </section>
    </div>
  );
}

function QuestEntry({ busyId, onAction, quest, compact = false, trackedId }) {
  const [open, setOpen] = useState(!compact);
  const showDetail = !compact || open;
  const objectiveLabel = { collect: "Collect", kill: "Defeat", talk: "Talk to" };
  return (
    <article className="quest-tracker-entry">
      <div className="quest-tracker-heading">
        <strong>{quest.title}</strong>
        <span className={`quest-status ${quest.status}`}>{quest.status}</span>
      </div>
      {compact && (
        <div className="quest-entry-actions">
          <button onClick={() => setOpen((value) => !value)} type="button">{open ? "Hide details" : "Details"}</button>
          {quest.status === "active" && quest.id !== trackedId && (
            <button disabled={busyId === quest.id} onClick={() => onAction(quest, "track")} type="button">Make active</button>
          )}
        </div>
      )}
      {showDetail && (
        <>
          <p>{quest.description}</p>
          <small>Given by {quest.giver_name}</small>
          {quest.status === "active" && (
            <>
              {quest.current_step_title && <strong className="quest-step-title">{quest.current_step_title}</strong>}
              {quest.step_description && <p>{quest.step_description}</p>}
              {quest.objectives.map((objective) => (
                <p className="quest-objective" key={objective.id}>
                  {objectiveLabel[objective.type] || "Visit"} {objective.target_name}: {objective.current}/{objective.required}
                </p>
              ))}
              {quest.can_choose && (
                <div className="quest-step-choices">
                  {quest.choices.map((choice) => (
                    <button
                      className="dialogue-choice-button"
                      disabled={busyId === quest.id}
                      key={choice.id}
                      onClick={() => onAction(quest, "choose", { step_id: quest.current_step_id, choice_id: choice.id })}
                      type="button"
                    >
                      {choice.text}
                    </button>
                  ))}
                </div>
              )}
              {quest.can_turn_in && <small>Return to {quest.giver_name} to claim your rewards.</small>}
            </>
          )}
        </>
      )}
    </article>
  );
}

function QuestTrackerSections({ busyId, onAction, quests, trackedId }) {
  const [collapsed, setCollapsed] = useState({});
  const active = quests.filter((quest) => quest.id === trackedId && quest.status === "active");
  const inProgress = quests.filter((quest) => quest.status === "active" && quest.id !== trackedId);
  const completed = quests.filter((quest) => quest.status === "completed");
  const sections = [
    ["active", "Active", active, false, "Your active quest guides the map and the star on the exits list."],
    ["progress", "In progress", inProgress, true, "Accepted quests. Pick one to make it your active quest."],
    ["completed", "Completed", completed, true, ""],
  ];
  return (
    <div className="quest-sections">
      {sections.map(([key, title, list, compact, hint]) => {
        const isCollapsed = Boolean(collapsed[key]);
        return (
          <section className="quest-section" key={key}>
            <button
              aria-expanded={!isCollapsed}
              className="quest-section-toggle"
              onClick={() => setCollapsed((current) => ({ ...current, [key]: !current[key] }))}
              type="button"
            >
              <span>{isCollapsed ? "▸" : "▾"} {title}</span>
              <small>{list.length}</small>
            </button>
            {!isCollapsed && (
              <div className="quest-section-body">
                {hint && list.length > 0 && <p className="studio-hint">{hint}</p>}
                {list.length ? list.map((quest) => (
                  <QuestEntry busyId={busyId} compact={compact} key={quest.id} onAction={onAction} quest={quest} trackedId={trackedId} />
                )) : <p className="world-empty">None</p>}
              </div>
            )}
          </section>
        );
      })}
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

