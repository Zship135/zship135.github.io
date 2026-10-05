import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, liveUrl } from "./api.js";
import ContentStudio from "./ContentStudio.jsx";

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

function upsertActivity(current, entry) {
  if (!entry.request_id) return [...current, entry].slice(-30);
  const existingIndex = current.findIndex((item) => item.request_id === entry.request_id);
  if (existingIndex === -1) return [...current, entry].slice(-30);
  return current.map((item, index) => index === existingIndex ? entry : item);
}

function activityMessageClass(message, entry) {
  if (entry.type === "location") return "world-text";
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
            {channel.id !== "global" && (
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
  const [canEditContent, setCanEditContent] = useState(false);
  const [studioMode, setStudioMode] = useState(false);
  const [channels, setChannels] = useState([{ id: "global", label: "World" }]);
  const [activeChannelId, setActiveChannelId] = useState("global");
  const [messagesByChannel, setMessagesByChannel] = useState({});
  const [profile, setProfile] = useState(null);
  const [command, setCommand] = useState("");
  const [commandBusy, setCommandBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const socketRef = useRef(null);
  const activityScrollRef = useRef(null);
  const followActivityRef = useRef(true);
  const previousAreaIdRef = useRef(null);
  const ambienceSequenceRef = useRef(0);
  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;
  const recoveringCommandsRef = useRef(false);
  const channelsRef = useRef(channels);
  channelsRef.current = channels;
  const activeChannelIdRef = useRef(activeChannelId);
  activeChannelIdRef.current = activeChannelId;
  const activeChannel = useMemo(
    () => channels.find((channel) => channel.id === activeChannelId) || channels[0],
    [activeChannelId, channels],
  );
  const messages = messagesByChannel[activeChannel.id] || [];

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
  }, [snapshot]);

  function showError(error) {
    if (error.status === 401) {
      sessionStorage.removeItem(TOKEN_KEY);
      setToken(null);
      sessionStorage.removeItem(ACCOUNT_KEY);
      setAccountId(null);
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
          await refreshMessages(token, "global");
          if (activeChannelIdRef.current !== "global") {
            await refreshMessages(token, activeChannelIdRef.current);
          }
          await recoverCommands(token, world.account_id);
          return;
        }
        if (data.type === "subscribed") {
          await refreshMessages(token, data.channel_id);
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
        if (data.type === "command.completed") {
          setActivity((current) => upsertActivity(current, data.payload));
          const world = await refreshWorld(token);
          if (!world) {
            socket.close();
            return;
          }
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
  }, [token, characterSetupPending, refreshWorld, refreshMessages, recoverCommands]);

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

  async function submitCommand(event) {
    event.preventDefault();
    const text = command.trim();
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
      sessionStorage.setItem(
        pendingCommandsKey(accountId),
        JSON.stringify(loadPendingCommands(accountId).filter((item) => item.request_id !== request.request_id)),
      );
      setActivity((current) => upsertActivity(current, result));
      setCommand("");
      await refreshWorld(token);
    } catch (error) {
      showError(error);
    } finally {
      setCommandBusy(false);
    }

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
      setActivity([]);
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
                entities={snapshot?.area?.exits || []}
                renderItem={(direction) => {
                  const destination = snapshot?.area?.exit_destinations?.[direction];
                  return (
                    <button key={direction} onClick={() => enterCommand(`travel ${direction}`)} type="button">
                      {direction}{destination ? ` → ${destination}` : ""}
                    </button>
                  );
                }}
              />
              <WorldEntityList title="NPCs" entities={snapshot?.area?.npcs || []} renderItem={(npc) => (
                <article className="world-entity npc-entity" key={npc.id}>
                  <strong>{npc.name}</strong><p>{npc.description}</p>
                  <button onClick={() => enterCommand(`talk to ${npc.name}`)} type="button">Talk</button>
                </article>
              )} />
              <WorldEntityList title="Enemies" entities={snapshot?.area?.enemies || []} renderItem={(enemy) => (
                <article className="world-entity enemy-entity" key={enemy.id}>
                  <strong>{enemy.name}</strong>
                  <span>HP {enemy.health}/{enemy.max_health} · D{enemy.attack_die_sides}</span>
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

      {profile && (
        <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setProfile(null); }}>
          <section aria-labelledby="profile-title" aria-modal="true" className="profile-dialog" role="dialog">
            <button aria-label="Close profile" className="dialog-close" onClick={() => setProfile(null)} type="button">×</button>
            <p className="eyebrow">TRAVELER PROFILE</p>
            <div className="profile-avatar">{profile.name.slice(0, 1).toUpperCase()}</div>
            <h2 id="profile-title">{profile.name}</h2>
            <p>{profile.species} · Last seen in {profile.area_name}</p>
            <button className="primary-button" onClick={() => openPrivateChat(profile.account_id, profile.name)} type="button">Open private chat</button>
          </section>
        </div>
      )}
    </div>
  );
}

function equipmentName(world, slot) {
  const itemId = world?.character?.equipment?.[slot] || "fist";
  if (itemId === "fist") return "Fist";
  const inventory = world?.character?.inventory || {};
  return itemId.replaceAll("_", " ") + (inventory[itemId] ? "" : " (unavailable)");
}

function WorldEntityList({ title, entities, renderItem }) {
  return (
    <section className="world-entity-group">
      <h3>{title}</h3>
      {entities.length ? entities.map(renderItem) : <p className="world-empty">None</p>}
    </section>
  );
}
