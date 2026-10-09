import { useEffect, useMemo, useState } from "react";
import { layoutMap, wrapLabel } from "./mapLayout.js";
import { api, apiBlob } from "./api.js";
import { restoreLocationSelection } from "./contentStudioSelection.js";
import { DiePreview } from "./Dice3D.jsx";

const SELECTED_LOCATION_KEY = "plight.content.selectedLocation";

const NAVIGATION = [
  ["map", "World map"],
  ["locations", "Locations"],
  ["audio", "Audio"],
  ["enemies", "Enemies"],
  ["npcs", "NPCs"],
  ["items", "Items"],
  ["weapons", "Weapons"],
  ["shields", "Shields"],
  ["armor", "Armor"],
  ["necklaces", "Necklaces"],
  ["rings", "Rings"],
  ["recipes", "Recipes"],
  ["quests", "Quests"],
  ["environment", "Furniture / objects"],
  ["resources", "Resources"],
  ["currencies", "Currencies"],
  ["enchantments", "Enchantments"],
  ["dieskins", "Die skins"],
];

const ITEM_TYPES = ["item", "weapon", "shield", "armor", "ring", "necklace"];
const ITEM_RESOURCE_TYPES = [...ITEM_TYPES, "resource"];
const ARMOR_SLOT_OPTIONS = [
  ["helm", "Helm"], ["tunic", "Tunic"], ["pants", "Pants"],
  ["sleeves", "Sleeves"], ["gloves", "Gloves"], ["boots", "Boots"],
].map(([id, name]) => ({ id, name }));
const PARTICLE_EFFECTS = [
  ["none", "None"], ["sparks", "Sparks"], ["embers", "Embers"], ["snow", "Snowflakes"],
  ["bubbles", "Bubbles"], ["stars", "Stars"], ["smoke", "Smoke"],
].map(([id, name]) => ({ id, name }));

const ACTION_SOUND_OPTIONS = [
  ["observe", "Observe"],
  ["talk", "Talk"],
  ["travel", "Travel"],
  ["attack", "Attack"],
  ["light_attack", "Light attack"],
  ["heavy_attack", "Heavy attack"],
  ["defend", "Defend"],
  ["wait", "Wait / rest"],
  ["gather", "Gather"],
  ["cancel_gather", "Cancel gathering"],
  ["craft", "Craft"],
  ["equip_item", "Equip item"],
  ["unequip_item", "Unequip item"],
  ["use_item", "Use item"],
  ["shop_buy", "Buy from shop"],
  ["shop_sell", "Sell to shop"],
  ["give_item", "Give item"],
  ["trade_offer", "Offer trade"],
  ["trade_accept", "Accept trade"],
  ["market_list", "List market item"],
  ["market_buy", "Buy market listing"],
  ["market_cancel", "Cancel market listing"],
].map(([id, name]) => ({ id, name }));

const ENTITY_TABS = {
  enemies: ["enemy", { health: 20, attack: 3, defense: 1, speed: 10, experience: 10 }],
  npcs: ["npc", { health: 100 }],
  items: ["item", { weight: 1, stack_size: 99, value: 1 }],
  weapons: ["weapon", { damage: 5, speed: 10, stamina_cost: 1, value: 10 }],
  shields: ["shield", { defense: 3, value: 10 }],
  armor: ["armor", { defense: 3, value: 10 }],
  necklaces: ["necklace", { value: 10 }],
  rings: ["ring", { value: 10 }],
  environment: ["furniture", { durability: 100 }],
  resources: ["resource", {}],
};

const CATEGORY_NAMES = {
  enemy: "Enemies",
  npc: "NPCs",
  item: "Items",
  weapon: "Weapons",
  shield: "Shields",
  armor: "Armor",
  necklace: "Necklaces",
  ring: "Rings",
  furniture: "Furniture",
  object: "Objects",
  resource: "Resources",
};

const SKILL_OPTIONS = [
  ["felling", "Felling"],
  ["foraging", "Foraging"],
  ["gouging", "Gouging"],
  ["fishing", "Fishing"],
  ["herbology", "Herbology"],
  ["alchemy", "Alchemy"],
  ["fletching", "Fletching"],
  ["smithing", "Smithing"],
  ["lapidary", "Lapidary"],
  ["woodworking", "Woodworking"],
].map(([id, name]) => ({ id, name }));
const GATHERING_SKILL_OPTIONS = SKILL_OPTIONS.slice(0, 5);

const NPC_RACE_GROUPS = [
  ["Common peoples", [
    "human", "elf", "high_elf", "wood_elf", "dark_elf", "sea_elf",
    "dwarf", "hill_dwarf", "mountain_dwarf", "gnome", "halfling",
    "orc", "half_orc", "goblin", "hobgoblin", "bugbear", "kobold",
    "ogre", "troll", "giant", "cyclops",
  ]],
  ["Fey and nature folk", [
    "fae", "fairy", "pixie", "sprite", "brownie", "dryad", "nymph",
    "satyr", "faun", "centaur", "minotaur", "changeling", "fey_touched",
    "plantfolk", "mushroom_folk", "slimefolk",
  ]],
  ["Sea and mythic folk", [
    "harpy", "siren", "mermaid", "merman", "merfolk", "selkie", "sea_folk",
    "triton", "naiad", "undine", "sylph", "salamander", "oni", "tengu",
    "kitsune", "kappa",
  ]],
  ["Elemental and constructed", [
    "elemental", "air_elemental", "earth_elemental", "fire_elemental",
    "water_elemental", "djinn", "genie", "golem", "construct", "automaton",
    "homunculus",
  ]],
  ["Scaled and beast folk", [
    "dragon", "dragonkin", "draconic", "drakefolk", "lizardfolk", "snakefolk",
    "beastfolk", "catfolk", "wolfkin", "foxfolk", "ratfolk", "bearfolk",
    "boarfolk", "rabbitfolk", "deerfolk", "lionfolk", "birdfolk", "avian",
    "insectfolk", "mothfolk", "spiderfolk", "fishfolk", "sharkfolk",
    "turtlefolk", "octopoid", "amphibian", "reptilian",
  ]],
  ["Undead", [
    "vampire", "dhampir", "werewolf", "lycanthrope", "undead", "revenant",
    "skeleton", "ghost", "ghoul", "lich", "mummy", "zombie",
  ]],
  ["Celestial, fiendish, and otherworldly", [
    "angel", "celestial", "nephilim", "demon", "devil", "fiend", "spirit",
    "shadowborn", "starborn", "dreamborn", "void_touched", "shapeshifter",
    "half_elf", "half_giant", "half_dragon", "half_fae",
  ]],
].map(([label, races]) => ({
  label,
  options: races.map((id) => ({
    id,
    name: id.split("_").map((word) => word[0].toUpperCase() + word.slice(1)).join(" "),
  })),
}));

const OPPOSITE_EXIT = { north: "south", south: "north", east: "west", west: "east" };

function makeId(label, existingIds) {
  const base = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const safeBase = /^[a-z]/.test(base) ? base : `entity_${base || "new"}`;
  let id = safeBase.slice(0, 64);
  let suffix = 2;
  while (existingIds.has(id)) {
    const ending = `_${suffix++}`;
    id = `${safeBase.slice(0, 64 - ending.length)}${ending}`;
  }
  return id;
}

function Field({ label, value, onChange, type = "text", min, max, step, placeholder }) {
  return (
    <label className="studio-field">
      <span>{label}</span>
      <input
        max={max}
        min={min}
        onChange={(event) => onChange(type === "number" ? Number(event.target.value) : event.target.value)}
        placeholder={placeholder}
        step={step}
        type={type}
        value={value}
      />
    </label>
  );
}

function TextAreaField({ label, value, onChange, rows = 4 }) {
  return (
    <label className="studio-field">
      <span>{label}</span>
      <textarea onChange={(event) => onChange(event.target.value)} rows={rows} value={value} />
    </label>
  );
}

function AudioAssetField({ label, assetId, token, onChange, onUploadStateChange, onUploaded, disabled }) {
  const [previewUrl, setPreviewUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!assetId) {
      setPreviewUrl("");
      return undefined;
    }
    setPreviewUrl("");
    setError("");
    let stale = false;
    let objectUrl = "";
    apiBlob(`/api/v1/content/audio/${encodeURIComponent(assetId)}`, { token })
      .then((blob) => {
        if (stale) return;
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
        setError("");
      })
      .catch((requestError) => {
        if (!stale) setError(requestError.message);
      });
    return () => {
      stale = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [assetId, token]);

  async function upload(file) {
    if (!file) return;
    setError("");
    if (file.size > 25 * 1024 * 1024) {
      setError("MP3 files may not exceed 25 MiB.");
      return;
    }
    setBusy(true);
    onUploadStateChange(true);
    try {
      const uploaded = await api("/api/v1/content/audio", {
        token,
        method: "POST",
        body: file,
        headers: { "Content-Type": "audio/mpeg" },
      });
      onChange(uploaded.asset_id);
      onUploaded();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
      onUploadStateChange(false);
    }
  }

  return (
    <div className="studio-audio-field">
      <p>{label}</p>
      {previewUrl ? (
        <audio aria-label={`${label} preview`} controls preload="none" src={previewUrl} />
      ) : <span className="studio-hint">{error ? "Preview unavailable." : assetId ? "Loading audio preview…" : "No MP3 assigned."}</span>}
      <div className="studio-audio-actions">
        <label className="studio-secondary-button">
          {busy ? "Uploading…" : "Upload MP3"}
          <input
            accept=".mp3,audio/mpeg"
            disabled={disabled || busy}
            onChange={(event) => {
              void upload(event.target.files?.[0]);
              event.target.value = "";
            }}
            type="file"
          />
        </label>
        {assetId && <button className="text-button" disabled={disabled || busy} onClick={() => onChange(null)} type="button">Clear assignment</button>}
      </div>
      <span className="studio-hint">MP3 audio, up to 25 MiB. Uploaded files are kept on the game server.</span>
      {error && <span className="studio-audio-error" role="alert">{error}</span>}
    </div>
  );
}

function TextBlockList({ title, hint, entries = [], onChange }) {
  return (
    <section className="studio-subsection studio-ambience-editor">
      <div className="studio-subsection-heading">
        <div><h3>{title}</h3><p>{hint}</p></div>
        <button className="studio-small-button" onClick={() => onChange([...entries, ""])} type="button">Add text block</button>
      </div>
      {entries.map((text, index) => (
        <div className="studio-ambience-entry" key={index}>
          <label className="studio-field">
            <span>Text block {index + 1}</span>
            <textarea maxLength={1000} onChange={(event) => onChange(entries.map((entry, entryIndex) => entryIndex === index ? event.target.value : entry))} placeholder="Write a short ambient line…" rows={3} value={text} />
          </label>
          <button aria-label={`Delete text block ${index + 1}`} className="studio-remove-button" onClick={() => onChange(entries.filter((_, entryIndex) => entryIndex !== index))} type="button">×</button>
        </div>
      ))}
      {entries.length === 0 && <p className="studio-hint">No ambience text yet. Add a text block to give this content a voice.</p>}
    </section>
  );
}

function SelectField({ label, value, options, onChange, emptyLabel }) {
  return (
    <label className="studio-field">
      <span>{label}</span>
      <select onChange={(event) => onChange(event.target.value || null)} value={value || ""}>
        {emptyLabel && <option value="">{emptyLabel}</option>}
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.name}</option>
        ))}
      </select>
    </label>
  );
}

function EntityPicker({ title, options, selected, onToggle, emptyMessage = "Nothing here yet." }) {
  return (
    <fieldset className="studio-picker">
      <legend>{title}</legend>
      {options.length === 0 ? <p className="studio-hint">{emptyMessage}</p> : (
        <div className="studio-check-list">
          {options.map((item) => (
            <label key={item.id}>
              <input checked={selected.includes(item.id)} onChange={(event) => onToggle(item.id, event.target.checked)} type="checkbox" />
              <span>{item.name}</span>
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

function WorldMap({ content, onSelect }) {
  const locations = content.locations;
  const cells = layoutMap(locations, content.selectedLocationId || locations[0]?.id);
  const CELL_W = 230;
  const CELL_H = 120;
  const points = new Map(locations.map((location) => {
    const cell = cells.get(location.id) || { x: 0, y: 0 };
    return [location.id, { x: cell.x * CELL_W, y: cell.y * CELL_H }];
  }));
  const coords = [...points.values()];
  const minX = Math.min(0, ...coords.map((point) => point.x)) - CELL_W / 2;
  const maxX = Math.max(0, ...coords.map((point) => point.x)) + CELL_W / 2;
  const minY = Math.min(0, ...coords.map((point) => point.y)) - CELL_H / 2;
  const maxY = Math.max(0, ...coords.map((point) => point.y)) + CELL_H / 2;
  const links = new Map();
  for (const location of locations) {
    for (const [direction, destinationId] of Object.entries(location.exits)) {
      if (!points.has(destinationId)) continue;
      const pair = [location.id, destinationId].sort().join("|");
      const link = links.get(pair) || { id: pair, from: location.id, to: destinationId, directions: [], twoWay: false };
      if (link.directions.length && link.from !== location.id) link.twoWay = true;
      link.directions.push(`${location.id === link.from ? "" : "← "}${direction}`);
      links.set(pair, link);
    }
  }

  return (
    <div className="studio-map-scroll">
      <svg
        aria-label="Map of connected world locations"
        className="studio-map"
        role="img"
        style={{ width: Math.max(600, maxX - minX), height: Math.max(360, maxY - minY) }}
        viewBox={`${minX} ${minY} ${maxX - minX} ${maxY - minY}`}
      >
        <defs>
          <marker id="map-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="6" refY="3" viewBox="0 0 6 6">
            <path d="M0,0 L6,3 L0,6" fill="none" stroke="#c78248" strokeWidth="1.2" />
          </marker>
        </defs>
        {[...links.values()].map((link) => {
          const a = points.get(link.from);
          const b = points.get(link.to);
          return (
            <g className="studio-map-link" key={link.id}>
              <line markerEnd={link.twoWay ? undefined : "url(#map-arrow)"} x1={a.x} x2={b.x} y1={a.y} y2={b.y} />
            </g>
          );
        })}
        {locations.map((location) => {
          const { x, y } = points.get(location.id);
          const selected = location.id === content.selectedLocationId;
          const kinds = [
            location.enemy_ids.length && `${location.enemy_ids.length} enemy`,
            location.npc_ids.length && `${location.npc_ids.length} NPC`,
          ].filter(Boolean).join(" / ");
          return (
            <g
              aria-label={`${location.name}, ${Object.keys(location.exits || {}).length} exits`}
              className={`studio-map-node ${selected ? "selected" : ""}`}
              key={location.id}
              onClick={() => onSelect(location.id)}
              role="button"
              tabIndex="0"
              transform={`translate(${x} ${y})`}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelect(location.id);
              }}
            >
              <rect height="64" rx="4" width="176" x="-88" y="-32" />
              <text className="studio-map-node-name" y="-3">{wrapLabel(location.name, 24)[0]}</text>
              <text className="studio-map-node-meta" y="17">{kinds || "Quiet location"}</text>
            </g>
          );
        })}
        {locations.length === 0 && <text className="studio-map-empty" x="0" y="0">Create a location to start your map.</text>}
      </svg>
    </div>
  );
}

export default function ContentStudio({ token, onClose, onSignOut }) {
  const [content, setContent] = useState(null);
  const [revision, setRevision] = useState("");
  const [tab, setTab] = useState("map");
  const [selectedId, setSelectedId] = useState(() => sessionStorage.getItem(SELECTED_LOCATION_KEY) || "");
  const [busy, setBusy] = useState(false);
  const [pendingAudioUploads, setPendingAudioUploads] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [linkForm, setLinkForm] = useState({ from: "", to: "", direction: "east" });

  async function loadContent() {
    setError("");
    setBusy(true);
    try {
      const result = await api("/api/v1/content", { token });
      const nextSelectedId = restoreLocationSelection(
        result.content.locations,
        selectedId,
        sessionStorage.getItem(SELECTED_LOCATION_KEY),
      );
      setContent(result.content);
      setRevision(result.revision);
      setSelectedId(nextSelectedId);
      if (result.content.locations.some((location) => location.id === nextSelectedId)) {
        sessionStorage.setItem(SELECTED_LOCATION_KEY, nextSelectedId);
      }
      setLinkForm({
        from: result.content.locations[0]?.id || "",
        to: result.content.locations[1]?.id || "",
        direction: "east",
      });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { loadContent(); }, [token]);

  const entitiesById = useMemo(
    () => new Map((content?.entities || []).map((entity) => [entity.id, entity])),
    [content],
  );
  const recipes = content?.recipes || [];
  const quests = content?.quests || [];
  const currencies = content?.currencies || [];
  const enchantments = content?.enchantments || [];
  const dieSkins = content?.die_skins || [];
  const currentDieSkin = tab === "dieskins" ? dieSkins.find((item) => item.id === selectedId) : null;
  const currentEnchantment = tab === "enchantments" ? enchantments.find((item) => item.id === selectedId) : null;
  const currentCurrency = tab === "currencies" ? currencies.find((currency) => currency.id === selectedId) : null;
  const currentLocation = content?.locations.find((location) => location.id === selectedId);
  const currentRecipe = recipes.find((recipe) => recipe.id === selectedId);
  const currentQuest = quests.find((quest) => quest.id === selectedId);
  const currentEntity = Object.keys(ENTITY_TABS).includes(tab)
    ? (content?.entities || []).find((entity) => entity.id === selectedId)
    : null;
  const currentActionSound = tab === "audio"
    ? ACTION_SOUND_OPTIONS.find((action) => action.id === selectedId)
    : null;
  const visibleEntities = useMemo(() => {
    if (!content) return [];
    if (tab === "environment") return content.entities.filter((entity) => ["furniture", "object"].includes(entity.type));
    const entityType = ENTITY_TABS[tab]?.[0];
    return entityType ? content.entities.filter((entity) => entity.type === entityType) : [];
  }, [content, tab]);
  const currentEntries = tab === "audio"
    ? ACTION_SOUND_OPTIONS
    : tab === "locations"
      ? content?.locations || []
        : tab === "dieskins"
          ? dieSkins
        : tab === "enchantments"
          ? enchantments
        : tab === "currencies"
          ? currencies
          : tab === "recipes"
          ? recipes
        : tab === "quests"
          ? quests
          : visibleEntities;

  function updateContent(mutator) {
    setContent((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      mutator(next);
      return next;
    });
    setNotice("");
  }

  function updateAudioUploadCount(uploading) {
    setPendingAudioUploads((count) => Math.max(0, count + (uploading ? 1 : -1)));
  }

  function selectLocation(id) {
    setSelectedId(id);
    sessionStorage.setItem(SELECTED_LOCATION_KEY, id);
  }

  function changeTab(nextTab) {
    setTab(nextTab);
    const nextList = nextTab === "audio"
      ? ACTION_SOUND_OPTIONS
      : nextTab === "locations"
        ? content.locations
        : nextTab === "map"
          ? content.locations
          : nextTab === "dieskins"
            ? content.die_skins || []
          : nextTab === "enchantments"
            ? content.enchantments || []
          : nextTab === "currencies"
            ? content.currencies || []
            : nextTab === "recipes"
            ? content.recipes
            : nextTab === "quests"
              ? content.quests
              : (content.entities || []).filter((entity) =>
                nextTab === "environment"
                  ? ["furniture", "object"].includes(entity.type)
                  : entity.type === ENTITY_TABS[nextTab]?.[0],
              );
    const selectedLocation = nextTab === "locations" || nextTab === "map"
      ? nextList.find((entry) => entry.id === selectedId)
        || nextList.find((entry) => entry.id === sessionStorage.getItem(SELECTED_LOCATION_KEY))
      : null;
    const nextSelectedId = selectedLocation?.id || nextList[0]?.id || "";
    setSelectedId(nextSelectedId);
    if ((nextTab === "locations" || nextTab === "map") && nextSelectedId) {
      sessionStorage.setItem(SELECTED_LOCATION_KEY, nextSelectedId);
    }
  }

  function createEntry() {
    if (tab === "locations") {
      const id = makeId("new_location", new Set(content.locations.map((location) => location.id)));
      updateContent((next) => {
        next.locations.push({
          id,
          name: "New location",
          description: "",
          position: { x: 50, y: 50 },
          music_asset_id: null,
          starting_species: [],
          exits: {},
          exit_requirements: {},
          ambience: [],
          enemy_ids: [],
          enemy_spawn_limit: 1,
          npc_ids: [],
          object_ids: [],
          resource_ids: [],
        });
      });
      selectLocation(id);
      return;
    }
    if (tab === "quests") {
      const giver = content.entities.find((entity) => entity.type === "npc");
      const item = content.entities.find((entity) => ITEM_RESOURCE_TYPES.includes(entity.type));
      const enemy = content.entities.find((entity) => entity.type === "enemy");
      const location = content.locations[0];
      if (!giver || (!item && !enemy && !location)) {
        setError("Create an NPC and at least one objective target before adding a quest.");
        return;
      }
      const id = makeId("new_quest", new Set(quests.map((quest) => quest.id)));
      const objective = item
        ? { id: "objective_1", type: "collect", target_id: item.id, quantity: 1 }
        : enemy
          ? { id: "objective_1", type: "kill", target_id: enemy.id, quantity: 1 }
          : { id: "objective_1", type: "visit", target_id: location.id, quantity: 1 };
      updateContent((next) => {
        next.quests.push({
          id,
          title: "New quest",
          description: "",
          giver_npc_id: giver.id,
          start_step_id: "step_1",
          steps: [{
            id: "step_1",
            title: "First step",
            description: "",
            objectives: [objective],
            choices: [{ id: "finish", text: "Return to the quest giver", next_step_id: null }],
          }],
          reward_experience: 50,
          reward_items: [],
          reward_currencies: [],
        });
      });
      setSelectedId(id);
      return;
    }
    if (tab === "dieskins") {
      const id = makeId("new_die_skin", new Set(dieSkins.map((item) => item.id)));
      updateContent((next) => {
        next.die_skins = [...(next.die_skins || []), {
          id, name: "New die skin", description: "", face_color: "#856432", edge_color: "#d9c67a",
          number_color: "#f3e7b0", glow_color: null, particle_effect: "sparks", particle_color: "#ffd27a",
        }];
      });
      setSelectedId(id);
      return;
    }
    if (tab === "enchantments") {
      const id = makeId("new_enchantment", new Set(enchantments.map((item) => item.id)));
      updateContent((next) => {
        next.enchantments = [...(next.enchantments || []), {
          id, name: "New enchantment", description: "", kind: "enchantment",
          effects: [{ type: "stat_modifier", stat: "attack", mode: "flat", amount: 1 }],
        }];
      });
      setSelectedId(id);
      return;
    }
    if (tab === "currencies") {
      const id = makeId("new_currency", new Set(currencies.map((currency) => currency.id)));
      updateContent((next) => {
        next.currencies = [...(next.currencies || []), { id, name: "New currency", symbol: "", description: "" }];
      });
      setSelectedId(id);
      return;
    }
    if (tab === "recipes") {
      const product = content.entities.find((entity) => ITEM_TYPES.includes(entity.type));
      const ingredient = content.entities.find((entity) => ITEM_RESOURCE_TYPES.includes(entity.type));
      if (!product || !ingredient) {
        setError("Create at least one item, weapon, or shield and one ingredient before adding a recipe.");
        return;
      }
      const id = makeId("new_recipe", new Set(content.recipes.map((recipe) => recipe.id)));
      updateContent((next) => {
        next.recipes.push({
          id,
          name: "New recipe",
          output_item_id: product.id,
          output_quantity: 1,
          ingredients: [{ item_id: ingredient.id, quantity: 1 }],
          station_id: null,
          skill: "",
          skill_level: 0,
        });
      });
      setSelectedId(id);
      return;
    }
    const [type, defaultAttributes] = ENTITY_TABS[tab] || [];
    if (!type) return;
    const id = makeId(`new_${type}`, new Set(content.entities.map((entity) => entity.id)));
    updateContent((next) => {
      next.entities.push({
        id,
        type,
        name: `New ${CATEGORY_NAMES[type].toLowerCase().replace(/s$/, "")}`,
        description: "",
        attributes: { ...defaultAttributes },
        ...(type === "furniture" || type === "object" ? { interaction_effect: null } : {}),
        ...(type === "item" ? { item_use: null } : {}),
        ...(ITEM_TYPES.includes(type) ? { enchantment_ids: [], is_map: false } : {}),
        ...(type === "armor" ? { armor_slot: "tunic" } : {}),
        ...(type === "resource" ? { gathering: null } : {}),
        ...(type === "enemy" ? {
          attack_die_sides: 2,
          respawn_chance_percent: 0,
          aggressive_attack_chance_percent: 0,
          behavior: "neutral",
          currency_drops: [],
        } : {}),
        ...(type === "npc" ? {
          race: "human",
          present_for: ["human", "goblin"],
          dialogue: { start_node_id: null, nodes: [] },
        } : {}),
        ambience: [],
        stock: [],
        buy_list: [],
        weapon_ids: [],
        loot_table: [],
      });
    });
    setSelectedId(id);
  }

  function deleteEntry() {
    const name = currentLocation?.name || currentRecipe?.name || currentQuest?.title || currentEntity?.name || currentCurrency?.name || currentEnchantment?.name || currentDieSkin?.name;
    if (!name || !window.confirm(`Delete "${name}"? References to this content will be removed.`)) return;
    updateContent((next) => {
      if (tab === "dieskins") {
        next.die_skins = (next.die_skins || []).filter((item) => item.id !== selectedId);
        for (const quest of next.quests) {
          if (quest.reward_die_skin_ids) quest.reward_die_skin_ids = quest.reward_die_skin_ids.filter((id) => id !== selectedId);
        }
      } else if (tab === "enchantments") {
        next.enchantments = (next.enchantments || []).filter((item) => item.id !== selectedId);
        for (const entity of next.entities) {
          if (entity.enchantment_ids) entity.enchantment_ids = entity.enchantment_ids.filter((id) => id !== selectedId);
        }
      } else if (tab === "currencies") {
        next.currencies = (next.currencies || []).filter((currency) => currency.id !== selectedId);
        for (const entity of next.entities) {
          if (entity.currency_drops) entity.currency_drops = entity.currency_drops.filter((drop) => drop.currency_id !== selectedId);
          for (const entry of entity.stock || []) {
            if (entry.currency_id === selectedId) entry.currency_id = null;
          }
          for (const entry of entity.buy_list || []) {
            if (entry.currency_id === selectedId) entry.currency_id = null;
          }
        }
        for (const quest of next.quests) {
          if (quest.reward_currencies) quest.reward_currencies = quest.reward_currencies.filter((reward) => reward.currency_id !== selectedId);
        }
      } else if (tab === "locations") {
        const removedQuestIds = next.quests
          .filter((quest) => quest.steps.some((step) => step.objectives.some(
            (objective) => objective.type === "visit" && objective.target_id === selectedId,
          )))
          .map((quest) => quest.id);
        next.quests = next.quests.filter((quest) => !removedQuestIds.includes(quest.id));
        next.locations = next.locations.filter((location) => location.id !== selectedId);
        for (const location of next.locations) {
          for (const [direction, destination] of Object.entries(location.exits)) {
            if (destination === selectedId) {
              delete location.exits[direction];
              delete location.exit_requirements?.[direction];
            }
            if (removedQuestIds.includes(location.exit_requirements?.[direction])) {
              delete location.exit_requirements[direction];
            }
          }
        }
      } else if (tab === "recipes") {
        next.recipes = next.recipes.filter((recipe) => recipe.id !== selectedId);
      } else if (tab === "quests") {
        next.quests = next.quests.filter((quest) => quest.id !== selectedId);
        for (const location of next.locations) {
          for (const [direction, questId] of Object.entries(location.exit_requirements || {})) {
            if (questId === selectedId) delete location.exit_requirements[direction];
          }
        }
      } else {
        const removed = entitiesById.get(selectedId);
        next.entities = next.entities.filter((entity) => entity.id !== selectedId);
        const removedQuestIds = next.quests
          .filter((quest) => quest.giver_npc_id === selectedId
              || quest.reward_items?.some((reward) => reward.item_id === selectedId)
              || quest.steps.some((step) => step.objectives.some(
                (objective) => objective.type !== "visit" && objective.target_id === selectedId,
              )))
          .map((quest) => quest.id);
        next.quests = next.quests.filter((quest) => !removedQuestIds.includes(quest.id));
        for (const location of next.locations) {
          for (const key of ["enemy_ids", "npc_ids", "object_ids", "resource_ids"]) {
            location[key] = location[key].filter((entityId) => entityId !== selectedId);
          }
          for (const [direction, questId] of Object.entries(location.exit_requirements || {})) {
            if (removedQuestIds.includes(questId)) delete location.exit_requirements[direction];
          }
        }
        for (const entity of next.entities) {
          entity.stock = entity.stock.filter((entry) => entry.item_id !== selectedId);
          if (entity.buy_list) entity.buy_list = entity.buy_list.filter((entry) => entry.item_id !== selectedId);
          entity.weapon_ids = entity.weapon_ids.filter((weaponId) => weaponId !== selectedId);
        }
        next.recipes = next.recipes.filter((recipe) =>
          recipe.output_item_id !== selectedId && recipe.station_id !== selectedId,
        );
        for (const recipe of next.recipes) {
          recipe.ingredients = recipe.ingredients.filter((entry) => entry.item_id !== selectedId);
        }
        next.recipes = next.recipes.filter((recipe) => recipe.ingredients.length > 0);
        if (ITEM_RESOURCE_TYPES.includes(removed?.type)) {
          for (const entity of next.entities) {
            entity.stock = entity.stock.filter((entry) => entry.item_id !== selectedId);
          }
        }
      }
    });
    setSelectedId("");
  }

  async function giveToSelf(kind, id, quantity = 1) {
    setError("");
    try {
      const result = await api("/api/v1/content/give", {
        token, method: "POST", body: JSON.stringify({ kind, id, quantity }),
      });
      setNotice(result.message);
    } catch (giveError) {
      setError(giveError.message);
    }
  }

  async function saveContent() {
    if (pendingAudioUploads > 0) {
      setError("Wait for the MP3 upload to finish before saving the world.");
      return;
    }
    const ambienceEntries = [
      ...content.locations.flatMap((location) => location.ambience || []),
      ...content.entities
        .filter((entity) => ["npc", "enemy"].includes(entity.type))
        .flatMap((entity) => entity.ambience || []),
    ];
    if (ambienceEntries.some((line) => !line.trim() || line.length > 1000)) {
      setError("Fill in or remove empty ambience text blocks. Each block can contain up to 1,000 characters.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api("/api/v1/content", {
        token,
        method: "PUT",
        body: JSON.stringify({ revision, content }),
      });
      setRevision(result.revision);
      setNotice(result.saved);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  function updateLocation(field, value) {
    updateContent((next) => {
      const location = next.locations.find((item) => item.id === selectedId);
      if (location) field(location, value);
    });
  }

  function updateEntity(field, value) {
    updateContent((next) => {
      const entity = next.entities.find((item) => item.id === selectedId);
      if (entity) field(entity, value);
    });
  }

  function addMapLink() {
    if (!linkForm.from || !linkForm.to || linkForm.from === linkForm.to) {
      setError("Choose two different locations to connect.");
      return;
    }
    updateContent((next) => {
      const from = next.locations.find((location) => location.id === linkForm.from);
      const to = next.locations.find((location) => location.id === linkForm.to);
      if (!from || !to) return;
      from.exits[linkForm.direction] = to.id;
      to.exits[OPPOSITE_EXIT[linkForm.direction]] = from.id;
    });
    setNotice(`Connected ${locationsById.get(linkForm.from)?.name || "location"} ${linkForm.direction} to ${locationsById.get(linkForm.to)?.name || "location"}. Save to activate the link.`);
  }

  const locationsById = new Map((content?.locations || []).map((location) => [location.id, location]));
  const eligibleItems = (content?.entities || []).filter((entity) => ITEM_RESOURCE_TYPES.includes(entity.type));
  const eligibleOutputs = (content?.entities || []).filter((entity) => ITEM_TYPES.includes(entity.type));
  const eligibleStations = (content?.entities || []).filter((entity) => ["furniture", "object"].includes(entity.type));

  return (
    <div className="studio-shell">
      <header className="studio-topbar">
        <a className="wordmark" href="#studio">PLIGHT <span>CONTENT STUDIO</span></a>
        <div className="studio-top-actions">
          <span className="studio-live-tag"><i /> ACTIVE WORLD DATA</span>
          <button className="text-button" onClick={onClose} type="button">Back to game</button>
          <button className="text-button" onClick={onSignOut} type="button">Sign out</button>
        </div>
      </header>
      <div className="studio-intro">
        <div>
          <p className="eyebrow">WORLD AUTHORING</p>
          <h1>Content studio</h1>
          <p>Edit your world in one place. Saving updates the active game data immediately.</p>
        </div>
        <div className="studio-actions">
          <button className="studio-secondary-button" disabled={busy || pendingAudioUploads > 0} onClick={loadContent} type="button">Reload</button>
          <button className="primary-button" disabled={busy || !content || pendingAudioUploads > 0} onClick={saveContent} type="button">
            {busy ? "Saving…" : pendingAudioUploads > 0 ? "Wait for MP3 upload…" : "Save to active world"}
          </button>
        </div>
      </div>
      {(error || notice) && (
        <div className={error ? "studio-message error-message" : "studio-message success-message"} role={error ? "alert" : "status"}>
          <span>{error || notice}</span>
          <button aria-label="Dismiss message" onClick={() => { setError(""); setNotice(""); }} type="button">×</button>
        </div>
      )}
      {busy && !content ? <div className="studio-loading">Loading world content…</div> : content && (
        <main className="studio-layout">
          <nav aria-label="World content sections" className="studio-nav">
            <p className="eyebrow">WORLD DATA</p>
            {NAVIGATION.map(([id, label]) => (
              <button aria-current={tab === id ? "page" : undefined} className={tab === id ? "active" : ""} key={id} onClick={() => changeTab(id)} type="button">
                <span>{label}</span>
                <small>{id === "map" || id === "locations" ? content.locations.length : id === "audio" ? Object.keys(content.action_sounds || {}).length : id === "recipes" ? content.recipes.length : id === "currencies" ? currencies.length : id === "enchantments" ? enchantments.length : id === "dieskins" ? dieSkins.length : id === "quests" ? quests.length : visibleCount(content, id)}</small>
              </button>
            ))}
            <div className="studio-nav-note">
              <span className="studio-live-tag"><i /> SAVE IS LIVE</span>
              <p>The game reads from this shared world file. Keep a backup before major edits.</p>
            </div>
          </nav>
          <section className="studio-workspace">
            {tab === "map" ? (
              <>
                <div className="studio-section-heading">
                  <div><p className="eyebrow">CONNECTED WORLD</p><h2>Location map</h2></div>
                  <button className="studio-secondary-button" onClick={() => changeTab("locations")} type="button">Manage locations</button>
                </div>
                <div className="studio-map-frame">
                  <WorldMap content={{ ...content, selectedLocationId: selectedId }} onSelect={(id) => { selectLocation(id); setTab("locations"); }} />
                </div>
                <div className="studio-map-controls">
                  <p>Connections create matching exits in both locations. The map is laid out automatically from each location\u2019s exits; select a node to edit it.</p>
                  <div className="studio-link-controls">
                    <SelectField label="From" options={content.locations} value={linkForm.from} onChange={(value) => setLinkForm((form) => ({ ...form, from: value || "" }))} />
                    <SelectField label="Direction" options={["north", "east", "south", "west"].map((name) => ({ id: name, name: name[0].toUpperCase() + name.slice(1) }))} value={linkForm.direction} onChange={(value) => setLinkForm((form) => ({ ...form, direction: value || "east" }))} />
                    <SelectField label="To" options={content.locations} value={linkForm.to} onChange={(value) => setLinkForm((form) => ({ ...form, to: value || "" }))} />
                    <button className="studio-secondary-button" onClick={addMapLink} type="button">Add connection</button>
                  </div>
                </div>
              </>
            ) : (
              <div className="studio-editor-layout">
                <aside className="studio-list-pane">
                  <div className="studio-list-heading">
                    <div><p className="eyebrow">{tab === "locations" ? "WORLD AREAS" : tab === "audio" ? "ACTION SOUNDS" : tab === "recipes" ? "CRAFTING" : "CATALOG"}</p><h2>{NAVIGATION.find(([id]) => id === tab)?.[1]}</h2></div>
                    {tab !== "audio" && (tab !== "locations" || content.locations.length > 0) ? (
                      <button aria-label={`Create ${tab === "locations" ? "location" : tab === "recipes" ? "recipe" : tab === "quests" ? "quest" : "entity"}`} className="studio-add-button" onClick={createEntry} type="button">+</button>
                    ) : null}
                  </div>
                  <div className="studio-entry-list">
                    {currentEntries.map((entry) => (
                      <button className={`studio-entry ${selectedId === entry.id ? "selected" : ""}`} key={entry.id} onClick={() => tab === "locations" ? selectLocation(entry.id) : setSelectedId(entry.id)} type="button">
                        <span>{tab === "quests" ? entry.title : entry.name}</span>
                        <small>{entry.id}</small>
                      </button>
                    ))}
                    {currentEntries.length === 0 && <p className="studio-empty">Nothing here yet. Use + to create one.</p>}
                  </div>
                  {(currentLocation || currentRecipe || currentQuest || currentEntity || currentCurrency || currentEnchantment || currentDieSkin) && (
                    <button className="studio-delete-button" onClick={deleteEntry} type="button">Delete selected</button>
                  )}
                </aside>
                <div className="studio-detail-pane">
                  {currentLocation && tab === "locations" && (
                    <LocationEditor
                      location={currentLocation}
                      entitiesById={entitiesById}
                      locations={content.locations}
                      quests={quests}
                      token={token}
                      onAudioUploaded={() => setNotice("MP3 uploaded. Save to active world to keep this assignment.")}
                      onUploadStateChange={updateAudioUploadCount}
                      audioDisabled={busy}
                      onChange={updateLocation}
                    />
                  )}
                  {currentActionSound && tab === "audio" && (
                    <ActionSoundEditor
                      action={currentActionSound}
                      assetId={content.action_sounds?.[currentActionSound.id] || null}
                      token={token}
                      onAudioUploaded={() => setNotice("MP3 uploaded. Save to active world to keep this assignment.")}
                      onUploadStateChange={updateAudioUploadCount}
                      audioDisabled={busy}
                      onChange={(assetId) => updateContent((next) => {
                        next.action_sounds ||= {};
                        if (assetId) next.action_sounds[currentActionSound.id] = assetId;
                        else delete next.action_sounds[currentActionSound.id];
                      })}
                    />
                  )}
                  {currentEntity && Object.keys(ENTITY_TABS).includes(tab) && (
                    <EntityEditor
                      entity={currentEntity}
                      locations={content.locations}
                      entities={content.entities}
                      currencies={currencies}
                      enchantments={enchantments}
                      onGive={giveToSelf}
                      lootItems={eligibleItems}
                      onChange={updateEntity}
                      onLocationToggle={(locationId, relationField, checked) => updateContent((next) => {
                        const location = next.locations.find((item) => item.id === locationId);
                        if (!location) return;
                        const values = location[relationField];
                        location[relationField] = checked
                          ? [...values, selectedId]
                          : values.filter((id) => id !== selectedId);
                      })}
                    />
                  )}
                  {currentEnchantment && tab === "enchantments" && (
                    <EnchantmentEditor
                      enchantment={currentEnchantment}
                      onChange={(field, value) => updateContent((next) => {
                        const item = next.enchantments.find((entry) => entry.id === selectedId);
                        if (item) item[field] = value;
                      })}
                    />
                  )}
                  {currentDieSkin && tab === "dieskins" && (
                    <DieSkinEditor
                      skin={currentDieSkin}
                      onGive={() => giveToSelf("die_skin", currentDieSkin.id)}
                      onChange={(field, value) => updateContent((next) => {
                        const skin = next.die_skins.find((item) => item.id === selectedId);
                        if (skin) skin[field] = value;
                      })}
                    />
                  )}
                  {currentCurrency && tab === "currencies" && (
                    <CurrencyEditor
                      currency={currentCurrency}
                      onChange={(field, value) => updateContent((next) => {
                        const currency = next.currencies.find((item) => item.id === selectedId);
                        if (currency) currency[field] = value;
                      })}
                    />
                  )}
                  {currentRecipe && tab === "recipes" && (
                    <RecipeEditor
                      recipe={currentRecipe}
                      outputs={eligibleOutputs}
                      ingredients={eligibleItems}
                      stations={eligibleStations}
                      onChange={(field, value) => updateContent((next) => {
                        const recipe = next.recipes.find((item) => item.id === selectedId);
                        if (recipe) field(recipe, value);
                      })}
                    />
                  )}
                  {currentQuest && tab === "quests" && (
                    <QuestEditor
                      quest={currentQuest}
                      npcs={content.entities.filter((entity) => entity.type === "npc")}
                      entities={content.entities}
                      currencies={currencies}
                      dieSkins={dieSkins}
                      locations={content.locations}
                      onChange={(field, value) => updateContent((next) => {
                        const quest = next.quests.find((item) => item.id === selectedId);
                        if (quest) field(quest, value);
                      })}
                    />
                  )}
                  {!currentLocation && !currentEntity && !currentRecipe && !currentQuest && !currentCurrency && !currentEnchantment && !currentDieSkin && <div className="studio-empty-detail">Select an entry or create a new one.</div>}
                </div>
              </div>
            )}
          </section>
        </main>
      )}
    </div>
  );
}

function visibleCount(content, tab) {
  if (tab === "environment") return content.entities.filter((entity) => ["furniture", "object"].includes(entity.type)).length;
  const type = ENTITY_TABS[tab]?.[0];
  return content.entities.filter((entity) => entity.type === type).length;
}

function LocationEditor({
  location,
  entitiesById,
  locations,
  quests,
  token,
  onChange,
  onUploadStateChange,
  onAudioUploaded,
  audioDisabled,
}) {
  function change(field, value) {
    onChange((current, nextValue) => { current[field] = nextValue; }, value);
  }

  function toggleId(field, id, selected) {
    onChange((current) => {
      const next = selected
        ? [...current[field], id]
        : current[field].filter((value) => value !== id);
      current[field] = next;
      if (field === "enemy_ids" && selected) {
        current.enemy_spawn_limit = Math.max(current.enemy_spawn_limit || 1, next.length);
      }
    });
  }

  const enemies = [...location.enemy_ids.map((id) => entitiesById.get(id)?.name).filter(Boolean)];
  const npcs = [...location.npc_ids.map((id) => entitiesById.get(id)?.name).filter(Boolean)];
  return (
    <div className="studio-form">
      <div className="studio-detail-heading">
        <div><p className="eyebrow">LOCATION / {location.id}</p><h2>{location.name}</h2></div>
        <span className="studio-kind-tag">AREA</span>
      </div>
      <Field label="Location name" value={location.name} onChange={(value) => change("name", value)} />
      <TextAreaField label="Description shown in the world" value={location.description} onChange={(value) => change("description", value)} />
      <section className="studio-subsection">
        <h3>Location music</h3>
        <p>This MP3 loops while players are in this location. Players can turn game audio on or off.</p>
        <AudioAssetField
          assetId={location.music_asset_id || null}
          label="Background music"
          token={token}
          onChange={(assetId) => change("music_asset_id", assetId)}
          onUploadStateChange={onUploadStateChange}
          onUploaded={onAudioUploaded}
          disabled={audioDisabled}
        />
      </section>
      <TextBlockList
        title="Location ambience"
        hint="One line is shown at random every 30 seconds while players are here."
        entries={location.ambience || []}
        onChange={(value) => change("ambience", value)}
      />
      <fieldset className="studio-picker">
        <legend>Starting location for</legend>
        <div className="studio-inline-checks">
          {["human", "goblin"].map((species) => (
            <label key={species}>
              <input checked={location.starting_species.includes(species)} onChange={(event) => change("starting_species", event.target.checked ? [...location.starting_species, species] : location.starting_species.filter((value) => value !== species))} type="checkbox" />
              <span>{species[0].toUpperCase() + species.slice(1)}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <section className="studio-subsection">
        <h3>Connected exits</h3>
        <p>Choose the destination reachable from each direction.</p>
        <div className="studio-exit-grid">
          {["north", "east", "south", "west"].map((direction) => (
            <SelectField
              key={direction}
              label={direction}
              options={locations.filter((item) => item.id !== location.id)}
              value={location.exits[direction]}
              onChange={(value) => onChange((current) => {
                if (value) current.exits[direction] = value;
                else delete current.exits[direction];
              })}
              emptyLabel="No exit"
            />
          ))}
        </div>
        <h4>Quest-gated exits</h4>
        <p>Players who have not completed the selected quest can see the exit but cannot use it.</p>
        <div className="studio-gate-list">
          {Object.keys(location.exits).map((direction) => (
            <SelectField
              key={direction}
              label={`${direction} exit requirement`}
              options={quests.map((quest) => ({ id: quest.id, name: quest.title }))}
              value={location.exit_requirements?.[direction]}
              onChange={(questId) => onChange((current) => {
                current.exit_requirements ||= {};
                if (questId) current.exit_requirements[direction] = questId;
                else delete current.exit_requirements[direction];
              })}
              emptyLabel="No quest required"
            />
          ))}
          {Object.keys(location.exits).length === 0 && <p className="studio-hint">Connect an exit before adding a gate.</p>}
        </div>
      </section>
      <section className="studio-subsection">
        <h3>Location population</h3>
        <p>Choose this location’s enemy types and maximum number of living enemy instances.</p>
        <Field
          label="Maximum enemies alive"
          min={Math.max(1, location.enemy_ids.length)}
          max={1000}
          onChange={(value) => change("enemy_spawn_limit", value)}
          type="number"
          value={location.enemy_spawn_limit ?? Math.max(1, location.enemy_ids.length)}
        />
        <EntityPicker title="Enemies" options={[...entitiesById.values()].filter((entity) => entity.type === "enemy")} selected={location.enemy_ids} onToggle={(id, selected) => toggleId("enemy_ids", id, selected)} />
        <EntityPicker title="NPCs" options={[...entitiesById.values()].filter((entity) => entity.type === "npc")} selected={location.npc_ids} onToggle={(id, selected) => toggleId("npc_ids", id, selected)} />
        <EntityPicker title="Furniture and objects" options={[...entitiesById.values()].filter((entity) => ["furniture", "object"].includes(entity.type))} selected={location.object_ids} onToggle={(id, selected) => toggleId("object_ids", id, selected)} />
        <EntityPicker title="Gatherable resources" options={[...entitiesById.values()].filter((entity) => entity.type === "resource")} selected={location.resource_ids} onToggle={(id, selected) => toggleId("resource_ids", id, selected)} />
        {(enemies.length > 0 || npcs.length > 0) && <p className="studio-hint">This area currently contains {[...enemies, ...npcs].join(", ")}.</p>}
      </section>
    </div>
  );
}

function ActionSoundEditor({
  action,
  assetId,
  token,
  onChange,
  onUploadStateChange,
  onAudioUploaded,
  audioDisabled,
}) {
  return (
    <div className="studio-form">
      <div className="studio-detail-heading">
        <div><p className="eyebrow">ACTION AUDIO / {action.id}</p><h2>{action.name}</h2></div>
        <span className="studio-kind-tag">GLOBAL</span>
      </div>
      <section className="studio-subsection">
        <h3>Sound effect</h3>
        <p>This MP3 plays when a player performs this action, in any location.</p>
        <AudioAssetField
          assetId={assetId}
          label={`${action.name} sound`}
          token={token}
          onChange={onChange}
          onUploadStateChange={onUploadStateChange}
          onUploaded={onAudioUploaded}
          disabled={audioDisabled}
        />
      </section>
    </div>
  );
}

function EntityEditor({ entity, entities, currencies = [], enchantments = [], locations, lootItems, onChange, onLocationToggle, onGive }) {
  const [giveQuantity, setGiveQuantity] = useState(1);
  const relationField = {
    enemy: "enemy_ids",
    npc: "npc_ids",
    furniture: "object_ids",
    object: "object_ids",
    resource: "resource_ids",
  }[entity.type];
  const stockOptions = entities.filter((item) => ITEM_RESOURCE_TYPES.includes(item.type));
  const weaponOptions = entities.filter((item) => item.type === "weapon");

  function set(field, value) {
    onChange((current) => { current[field] = value; });
  }

  function toggleLocation(locationId, checked) {
    if (!relationField) return;
    onLocationToggle(locationId, relationField, checked);
  }

  function setAttribute(key, value) {
    onChange((current) => { current.attributes[key] = value; });
  }

  function addAttribute() {
    const id = `stat_${Object.keys(entity.attributes).length + 1}`;
    setAttribute(id, 0);
  }

  function deleteAttribute(key) {
    onChange((current) => { delete current.attributes[key]; });
  }

  function setStock(index, field, value) {
    onChange((current) => { current.stock[index][field] = value; });
  }

  return (
    <div className="studio-form">
      <div className="studio-detail-heading">
        <div><p className="eyebrow">{CATEGORY_NAMES[entity.type].toUpperCase()} / {entity.id}</p><h2>{entity.name}</h2></div>
        <span className="studio-kind-tag">{entity.type.toUpperCase()}</span>
      </div>
      {["furniture", "object"].includes(entity.type) && (
        <>
          <SelectField
            label="Environment object type"
            options={[{ id: "furniture", name: "Furniture" }, { id: "object", name: "Other object" }]}
            value={entity.type}
            onChange={(value) => set("type", value)}
          />
          <p className="studio-hint">
            Crafting stations remain usable by being in the location. An interaction effect is triggered when a player uses this object.
          </p>
          <SelectField
            emptyLabel="No interaction effect"
            label="Interaction effect"
            options={[
              { id: "restore_health", name: "Restore health fully" },
              { id: "set_respawn", name: "Set respawn point to this location" },
            ]}
            value={entity.interaction_effect}
            onChange={(value) => set("interaction_effect", value)}
          />
        </>
      )}
      <Field label="Name" value={entity.name} onChange={(value) => set("name", value)} />
      <TextAreaField label="Description" value={entity.description} onChange={(value) => set("description", value)} />
      {ITEM_RESOURCE_TYPES.includes(entity.type) && (
        <div className="studio-give-row">
          <Field label="Quantity" min={1} max={9999} onChange={(value) => setGiveQuantity(Math.max(1, Number(value) || 1))} type="number" value={giveQuantity} />
          <button className="studio-secondary-button" onClick={() => onGive("item", entity.id, giveQuantity)} type="button">Give to me</button>
        </div>
      )}
      {entity.type === "npc" && (
        <>
          <label className="studio-field">
            <span>NPC race</span>
            <select onChange={(event) => set("race", event.target.value)} value={entity.race}>
              {NPC_RACE_GROUPS.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.options.map((race) => <option key={race.id} value={race.id}>{race.name}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <EntityPicker
            title="Present for player races"
            options={[{ id: "human", name: "Human players" }, { id: "goblin", name: "Goblin players" }]}
            selected={entity.present_for || []}
            onToggle={(race, selected) => set("present_for", selected
              ? [...(entity.present_for || []), race]
              : (entity.present_for || []).filter((value) => value !== race))}
            emptyMessage="This NPC will not appear for either race."
          />
          <DialogueEditor dialogue={entity.dialogue} onChange={(value) => set("dialogue", value)} />
        </>
      )}
      {["enemy", "npc"].includes(entity.type) && (
        <TextBlockList
          title={`${CATEGORY_NAMES[entity.type]} ambience`}
          hint="One line is shown at random every 30 seconds while this character is present."
          entries={entity.ambience || []}
          onChange={(value) => set("ambience", value)}
        />
      )}
      <section className="studio-subsection">
        <div className="studio-subsection-heading"><div><h3>Attributes and stats</h3><p>Values are shared with the game as typed data.</p></div><button className="studio-small-button" onClick={addAttribute} type="button">Add stat</button></div>
        {entity.type === "enemy" && (
          <>
            <p className="studio-hint">Each assigned location rolls this chance every 15 seconds while below its population cap. Set to 0 to disable respawning.</p>
            <Field
              label="Respawn chance per 15 seconds (%)"
              min={0}
              max={100}
              onChange={(value) => set("respawn_chance_percent", value)}
              type="number"
              value={entity.respawn_chance_percent ?? 0}
            />
            <SelectField
              label="Combat behavior"
              options={[
                { id: "passive", name: "Passive — never fights back" },
                { id: "neutral", name: "Neutral — retaliates when attacked" },
                { id: "aggressive", name: "Aggressive — attacks in combat and rolls outside combat" },
              ]}
              value={entity.behavior || "neutral"}
              onChange={(value) => set("behavior", value)}
            />
            {entity.behavior === "aggressive" && (
              <>
                <p className="studio-hint">
                  Each aggressive enemy instance independently rolls for each nearby player every 15 seconds outside combat. Set to 0 to disable these attacks.
                </p>
                <Field
                  label="Outside-combat hit chance per 15 seconds (%)"
                  min={0}
                  max={100}
                  onChange={(value) => set("aggressive_attack_chance_percent", value)}
                  type="number"
                  value={entity.aggressive_attack_chance_percent ?? 0}
                />
              </>
            )}
            <Field
              label="Attack die (number of sides)"
              min={2}
              max={100}
              onChange={(value) => set("attack_die_sides", value)}
              type="number"
              value={entity.attack_die_sides ?? 2}
            />
          </>
        )}
        {entity.type === "armor" && (
          <SelectField label="Body slot" options={ARMOR_SLOT_OPTIONS} value={entity.armor_slot} onChange={(value) => set("armor_slot", value || "tunic")} />
        )}
        <div className="studio-attribute-list">
          {Object.entries(entity.attributes).map(([key, value]) => (
            <div className="studio-attribute-row" key={key}>
              <input aria-label="Attribute name" onChange={(event) => {
                const nextKey = event.target.value;
                if (!nextKey.trim() || nextKey === key || Object.hasOwn(entity.attributes, nextKey)) return;
                onChange((current) => {
                  current.attributes[nextKey] = current.attributes[key];
                  delete current.attributes[key];
                });
              }} value={key} />
              <input
                aria-label={`${key} value`}
                onChange={(event) => {
                  const text = event.target.value;
                  const valueAsNumber = text.trim() === "" ? text : Number(text);
                  setAttribute(key, text.trim() !== "" && Number.isFinite(valueAsNumber) ? valueAsNumber : text);
                }}
                value={value}
              />
              <button aria-label={`Remove ${key}`} className="studio-remove-button" onClick={() => deleteAttribute(key)} type="button">×</button>
            </div>
          ))}
          {Object.keys(entity.attributes).length === 0 && <p className="studio-hint">No attributes. Add stats such as health, speed, damage, or value.</p>}
        </div>
      </section>
      {ITEM_TYPES.includes(entity.type) && (
        <section className="studio-subsection">
          <h3>Enchantments and curses</h3>
          <p className="studio-hint">
            {entity.type === "item"
              ? "Active while a player carries this item."
              : "Active while a player has this equipped."}
          </p>
          <label className="studio-field studio-inline-check">
            <span>Map item (lets the holder open the world map)</span>
            <input checked={Boolean(entity.is_map)} onChange={(event) => set("is_map", event.target.checked)} type="checkbox" />
          </label>
          {enchantments.map((item) => (
            <label className="studio-field studio-inline-check" key={item.id}>
              <span>{item.name}{item.kind === "curse" ? " (curse)" : ""}</span>
              <input
                checked={(entity.enchantment_ids || []).includes(item.id)}
                onChange={(event) => onChange((current) => {
                  const ids = new Set(current.enchantment_ids || []);
                  if (event.target.checked) ids.add(item.id); else ids.delete(item.id);
                  current.enchantment_ids = [...ids];
                })}
                type="checkbox"
              />
            </label>
          ))}
          {enchantments.length === 0 && <p className="studio-hint">Create enchantments in the Enchantments section first.</p>}
        </section>
      )}
      {entity.type === "item" && (
        <BookEditor book={entity.book} onChange={(value) => set("book", value)} />
      )}
      {entity.type === "item" && (
        <ItemUseEditor itemUse={entity.item_use} locations={locations} onChange={(value) => set("item_use", value)} />
      )}
      {entity.type === "resource" && (
        <ResourceGatheringEditor gathering={entity.gathering} items={lootItems} onChange={(value) => set("gathering", value)} />
      )}
      {entity.type === "enemy" && (
        <>
          <LootTableEditor entries={entity.loot_table || []} items={lootItems} onChange={(value) => set("loot_table", value)} />
          <CurrencyDropEditor entries={entity.currency_drops || []} currencies={currencies} onChange={(value) => set("currency_drops", value)} />
        </>
      )}
      {relationField && (
        <EntityPicker
          title="Present in locations"
          options={locations}
          selected={locations.filter((location) => location[relationField].includes(entity.id)).map((location) => location.id)}
          onToggle={(locationId, selected) => toggleLocation(locationId, selected)}
        />
      )}
      {entity.type === "npc" && (
        <>
          <EntityPicker title="Equipped weapons" options={weaponOptions} selected={entity.weapon_ids || []} onToggle={(id, selected) => set("weapon_ids", selected ? [...(entity.weapon_ids || []), id] : (entity.weapon_ids || []).filter((weaponId) => weaponId !== id))} emptyMessage="Create a weapon to equip one." />
          <section className="studio-subsection">
            <div className="studio-subsection-heading"><div><h3>Shop stock</h3><p>Items this NPC sells. Stock depletes per player and refills after the restock time. Choose a currency or the item cannot be bought.</p></div><button className="studio-small-button" disabled={stockOptions.length === 0} onClick={() => onChange((current) => {
              (current.stock ||= []).push({ item_id: stockOptions[0].id, quantity: 1, price: 1, currency_id: currencies[0]?.id || null, restock_seconds: 300 });
            })} type="button">Add stock</button></div>
            {(entity.stock || []).map((entry, index) => (
              <div className="studio-stock-row" key={`${entry.item_id}-${index}`}>
                <SelectField label="Item" options={stockOptions} value={entry.item_id} onChange={(value) => setStock(index, "item_id", value)} />
                <Field label="Quantity" min={0} onChange={(value) => setStock(index, "quantity", value)} type="number" value={entry.quantity} />
                <Field label="Price" min={0} onChange={(value) => setStock(index, "price", value)} type="number" value={entry.price} />
                <SelectField emptyLabel="Choose currency" label="Currency" options={currencies} value={entry.currency_id} onChange={(value) => setStock(index, "currency_id", value)} />
                <Field label="Restock (seconds)" min={1} onChange={(value) => setStock(index, "restock_seconds", value)} type="number" value={entry.restock_seconds ?? 300} />
                <button aria-label="Remove stock item" className="studio-remove-button" onClick={() => onChange((current) => { current.stock.splice(index, 1); })} type="button">×</button>
              </div>
            ))}
            {(entity.stock || []).length === 0 && <p className="studio-hint">This NPC is not selling anything.</p>}
          </section>
          <section className="studio-subsection">
            <div className="studio-subsection-heading"><div><h3>Buys from players</h3><p>Items this NPC purchases. Max per player is how many each player can sell before the reset time refreshes it.</p></div><button className="studio-small-button" disabled={stockOptions.length === 0} onClick={() => onChange((current) => {
              current.buy_list ||= [];
              current.buy_list.push({ item_id: stockOptions[0].id, quantity: 10, price: 1, currency_id: currencies[0]?.id || null, restock_seconds: 300 });
            })} type="button">Add buy entry</button></div>
            {(entity.buy_list || []).map((entry, index) => (
              <div className="studio-stock-row" key={`buy-${entry.item_id}-${index}`}>
                <SelectField label="Item" options={stockOptions} value={entry.item_id} onChange={(value) => onChange((current) => { current.buy_list[index].item_id = value; })} />
                <Field label="Max per player" min={0} onChange={(value) => onChange((current) => { current.buy_list[index].quantity = value; })} type="number" value={entry.quantity} />
                <Field label="Pays each" min={0} onChange={(value) => onChange((current) => { current.buy_list[index].price = value; })} type="number" value={entry.price} />
                <SelectField emptyLabel="Choose currency" label="Currency" options={currencies} value={entry.currency_id} onChange={(value) => onChange((current) => { current.buy_list[index].currency_id = value; })} />
                <Field label="Reset (seconds)" min={1} onChange={(value) => onChange((current) => { current.buy_list[index].restock_seconds = value; })} type="number" value={entry.restock_seconds ?? 300} />
                <button aria-label="Remove buy entry" className="studio-remove-button" onClick={() => onChange((current) => { current.buy_list.splice(index, 1); })} type="button">×</button>
              </div>
            ))}
            {(entity.buy_list || []).length === 0 && <p className="studio-hint">This NPC does not buy anything from players.</p>}
          </section>
        </>
      )}
    </div>
  );
}

function BookEditor({ book, onChange }) {
  const pages = book?.pages || [];
  function update(index, field, value) {
    onChange({ pages: pages.map((page, i) => (i === index ? { ...page, [field]: value } : page)) });
  }
  if (!book) {
    return (
      <section className="studio-subsection">
        <h3>Book</h3>
        <p className="studio-hint">Make this item a readable book. Using it opens a page-flipping reader.</p>
        <button className="studio-small-button" onClick={() => onChange({ pages: [{ title: "", text: "" }] })} type="button">Make this a book</button>
      </section>
    );
  }
  return (
    <section className="studio-subsection">
      <div className="studio-subsection-heading">
        <div><h3>Book pages</h3><p>Leave a blank line between paragraphs. Players flip through pages one at a time.</p></div>
        <div>
          <button className="studio-small-button" disabled={pages.length >= 200} onClick={() => onChange({ pages: [...pages, { title: "", text: "" }] })} type="button">Add page</button>
          <button className="studio-small-button" onClick={() => onChange(null)} type="button">Remove book</button>
        </div>
      </div>
      {pages.map((page, index) => (
        <section className="studio-effect-card" key={index}>
          <div className="studio-subsection-heading">
            <strong>Page {index + 1}</strong>
            <button aria-label={`Remove page ${index + 1}`} className="studio-remove-button" disabled={pages.length <= 1} onClick={() => onChange({ pages: pages.filter((_, i) => i !== index) })} type="button">×</button>
          </div>
          <Field label="Page title (optional)" onChange={(value) => update(index, "title", value)} value={page.title || ""} />
          <TextAreaField label="Text" onChange={(value) => update(index, "text", value)} rows={8} value={page.text} />
        </section>
      ))}
      <p className="studio-hint">Every page needs text before you can save.</p>
    </section>
  );
}

function ItemUseEditor({ itemUse, locations, onChange }) {
  const config = itemUse || { effects: [], target_scope: "self", consume_on_use: true };
  const effects = config.effects || [];

  function updateConfig(field, value) {
    onChange({ ...config, [field]: value, effects });
  }

  function updateEffect(index, field, value) {
    onChange({
      ...config,
      effects: effects.map((effect, effectIndex) => (
        effectIndex === index ? { ...effect, [field]: value } : effect
      )),
    });
  }

  function addEffect(type) {
    const defaults = {
      heal: { type, mode: "fixed", amount: 25 },
      stat_buff: { type, stat: "attack", mode: "flat", amount: 2, duration_seconds: 300 },
      shield: { type, mode: "damage_pool", amount: 20, duration_seconds: 300 },
      teleport: { type, destination_area_id: locations[0]?.id || "" },
      luck: { type, drop_chance_bonus_percent: 10, gathering_yield_bonus_percent: 0, duration_seconds: 300 },
    };
    onChange({ ...config, effects: [...effects, defaults[type]] });
  }

  if (!itemUse) {
    return (
      <section className="studio-subsection">
        <h3>Item effects</h3>
        <p className="studio-hint">Effects are applied when a player uses this item.</p>
        <button
          className="studio-small-button"
          onClick={() => onChange({ effects: [], target_scope: "self", consume_on_use: true })}
          type="button"
        >
          Enable item effects
        </button>
      </section>
    );
  }

  return (
    <section className="studio-subsection">
      <div className="studio-subsection-heading">
        <div><h3>Item effects</h3><p>Effects can be combined. Timed effects refresh when reapplied and do not stack their strength.</p></div>
        <button className="studio-small-button" onClick={() => onChange(null)} type="button">Disable effects</button>
      </div>
      <div className="studio-two-fields">
        <SelectField
          label="Targets"
          options={[
            { id: "self", name: "Only the user" },
            { id: "party", name: "User and online party members here" },
          ]}
          value={config.target_scope}
          onChange={(value) => updateConfig("target_scope", value)}
        />
        <label className="studio-field studio-inline-check">
          <span>Consume one item per use</span>
          <input
            checked={config.consume_on_use !== false}
            onChange={(event) => updateConfig("consume_on_use", event.target.checked)}
            type="checkbox"
          />
        </label>
      </div>
      {effects.map((effect, index) => (
        <section className="studio-effect-card" key={`${effect.type}-${index}`}>
          <div className="studio-subsection-heading">
            <strong>Effect {index + 1}</strong>
            <button
              aria-label={`Remove effect ${index + 1}`}
              className="studio-remove-button"
              onClick={() => onChange({ ...config, effects: effects.filter((_, effectIndex) => effectIndex !== index) })}
              type="button"
            >
              ×
            </button>
          </div>
          <SelectField
            label="Effect type"
            options={[
              { id: "heal", name: "Restore health" },
              { id: "stat_buff", name: "Boost a stat" },
              { id: "shield", name: "Shield" },
              { id: "teleport", name: "Teleport" },
              { id: "luck", name: "Luck" },
            ]}
            value={effect.type}
            onChange={(type) => {
              const defaults = {
                heal: { type, mode: "fixed", amount: 25 },
                stat_buff: { type, stat: "attack", mode: "flat", amount: 2, duration_seconds: 300 },
                shield: { type, mode: "damage_pool", amount: 20, duration_seconds: 300 },
                teleport: { type, destination_area_id: locations[0]?.id || "" },
                luck: { type, drop_chance_bonus_percent: 10, gathering_yield_bonus_percent: 0, duration_seconds: 300 },
              };
              onChange({
                ...config,
                effects: effects.map((current, effectIndex) => effectIndex === index ? defaults[type] : current),
              });
            }}
          />
          {effect.type === "heal" && (
            <div className="studio-two-fields">
              <SelectField
                label="Healing amount"
                options={[
                  { id: "fixed", name: "Fixed health" },
                  { id: "percent", name: "Percent of max health" },
                  { id: "full", name: "Restore to full" },
                ]}
                value={effect.mode}
                onChange={(value) => updateEffect(index, "mode", value)}
              />
              {effect.mode !== "full" && (
                <Field
                  label={effect.mode === "percent" ? "Health restored (%)" : "Health restored"}
                  min={1}
                  max={effect.mode === "percent" ? 100 : 10000}
                  onChange={(value) => updateEffect(index, "amount", value)}
                  type="number"
                  value={effect.amount}
                />
              )}
            </div>
          )}
          {effect.type === "stat_buff" && (
            <div className="studio-two-fields">
              <SelectField
                label="Stat"
                options={["attack", "defense", "speed"].map((id) => ({ id, name: id[0].toUpperCase() + id.slice(1) }))}
                value={effect.stat}
                onChange={(value) => updateEffect(index, "stat", value)}
              />
              <SelectField
                label="Bonus type"
                options={[{ id: "flat", name: "Flat points" }, { id: "percent", name: "Percent" }]}
                value={effect.mode}
                onChange={(value) => updateEffect(index, "mode", value)}
              />
              <Field label="Bonus amount" min={1} max={500} onChange={(value) => updateEffect(index, "amount", value)} type="number" value={effect.amount} />
              <Field label="Duration (seconds)" min={1} max={86400} onChange={(value) => updateEffect(index, "duration_seconds", value)} type="number" value={effect.duration_seconds} />
            </div>
          )}
          {effect.type === "shield" && (
            <div className="studio-two-fields">
              <SelectField
                label="Shield mode"
                options={[
                  { id: "damage_pool", name: "Absorb a total damage pool" },
                  { id: "damage_reduction", name: "Reduce each hit by a fixed amount" },
                  { id: "temporary_health", name: "Temporary health buffer" },
                ]}
                value={effect.mode}
                onChange={(value) => updateEffect(index, "mode", value)}
              />
              <Field label="Shield amount" min={1} max={100000} onChange={(value) => updateEffect(index, "amount", value)} type="number" value={effect.amount} />
              <Field label="Duration (seconds)" min={1} max={86400} onChange={(value) => updateEffect(index, "duration_seconds", value)} type="number" value={effect.duration_seconds} />
            </div>
          )}
          {effect.type === "teleport" && (
            <SelectField
              label="Destination"
              options={locations}
              value={effect.destination_area_id}
              onChange={(value) => updateEffect(index, "destination_area_id", value)}
            />
          )}
          {effect.type === "luck" && (
            <div className="studio-two-fields">
              <Field label="Loot drop chance bonus (%)" min={0} max={1000} onChange={(value) => updateEffect(index, "drop_chance_bonus_percent", value)} type="number" value={effect.drop_chance_bonus_percent} />
              <Field label="Gathering yield bonus (%)" min={0} max={1000} onChange={(value) => updateEffect(index, "gathering_yield_bonus_percent", value)} type="number" value={effect.gathering_yield_bonus_percent} />
              <Field label="Duration (seconds)" min={1} max={86400} onChange={(value) => updateEffect(index, "duration_seconds", value)} type="number" value={effect.duration_seconds} />
            </div>
          )}
        </section>
      ))}
      <label className="studio-field">
        <span>Add effect</span>
        <select onChange={(event) => {
          if (event.target.value) addEffect(event.target.value);
          event.target.value = "";
        }} value="">
          <option value="">Choose an effect…</option>
          <option value="heal">Restore health</option>
          <option value="stat_buff">Boost a stat</option>
          <option value="shield">Shield</option>
          <option value="teleport">Teleport</option>
          <option value="luck">Luck</option>
        </select>
      </label>
    </section>
  );
}

function ResourceGatheringEditor({ gathering, items, onChange }) {
  const config = gathering || {
    skill: "foraging",
    skill_level: 1,
    health: 100,
    tool_stat: null,
    minimum_tool_power: 0,
    respawn_seconds: 3600,
    loot_table: [],
  };

  if (!gathering) {
    return (
      <section className="studio-subsection">
        <h3>Gathering</h3>
        <p className="studio-hint">Enable harvesting configuration to make this resource gatherable.</p>
        <button className="studio-small-button" onClick={() => onChange(config)} type="button">Enable gathering</button>
      </section>
    );
  }

  function set(field, value) {
    onChange({ ...config, [field]: value });
  }

  return (
    <section className="studio-subsection">
      <div className="studio-subsection-heading">
        <div><h3>Gathering settings</h3><p>Harvest time is resource health × 60 ÷ (player skill level + equipped right-hand tool power).</p></div>
        <button className="studio-small-button" onClick={() => onChange(null)} type="button">Disable gathering</button>
      </div>
      <div className="studio-two-fields">
        <SelectField label="Required skill" options={GATHERING_SKILL_OPTIONS} value={config.skill} onChange={(value) => set("skill", value)} />
        <Field label="Required skill level" min={1} max={100} onChange={(value) => set("skill_level", value)} type="number" value={config.skill_level} />
        <Field label="Resource health" min={1} max={1000000} onChange={(value) => set("health", value)} type="number" value={config.health} />
        <Field label="Respawn time (seconds)" min={1} max={31536000} onChange={(value) => set("respawn_seconds", value)} type="number" value={config.respawn_seconds} />
        <Field label="Required tool stat (optional)" onChange={(value) => set("tool_stat", value || null)} value={config.tool_stat || ""} placeholder="e.g. gathering_power" />
        <Field label="Minimum tool power" min={0} max={1000000} onChange={(value) => set("minimum_tool_power", value)} type="number" value={config.minimum_tool_power} />
      </div>
      <LootTableEditor
        entries={config.loot_table || []}
        items={items}
        onChange={(value) => set("loot_table", value)}
        title="Gathering yield table"
        hint="Choose existing items, gear, or resources harvested from this node."
        emptyMessage="This resource will not yield anything until a drop is added."
      />
    </section>
  );
}

function LootTableEditor({
  entries,
  items,
  onChange,
  title = "Loot table",
  hint = "Choose an existing item, weapon/gear, or resource; set its drop chance and quantity range.",
  emptyMessage = "This enemy does not drop loot.",
}) {
  function updateEntry(index, field, value) {
    onChange(entries.map((entry, entryIndex) => (
      entryIndex === index ? { ...entry, [field]: value } : entry
    )));
  }

  return (
    <section className="studio-subsection">
      <div className="studio-subsection-heading">
        <div><h3>{title}</h3><p>{hint}</p></div>
        <button
          className="studio-small-button"
          disabled={items.length === 0}
          onClick={() => onChange([...entries, {
            item_id: items[0].id,
            chance: 0.5,
            minimum_quantity: 1,
            maximum_quantity: 1,
          }])}
          type="button"
        >
          Add drop
        </button>
      </div>
      {entries.map((entry, index) => (
        <div className="studio-loot-row" key={`${entry.item_id}-${index}`}>
          <SelectField
            label="Dropped item or gear"
            options={items}
            value={entry.item_id}
            onChange={(value) => updateEntry(index, "item_id", value)}
          />
          <Field
            label="Chance (%)"
            min={0}
            max={100}
            step={0.1}
            onChange={(value) => updateEntry(index, "chance", value / 100)}
            type="number"
            value={Number((entry.chance * 100).toFixed(1))}
          />
          <Field
            label="Minimum quantity"
            min={1}
            onChange={(value) => updateEntry(index, "minimum_quantity", value)}
            type="number"
            value={entry.minimum_quantity}
          />
          <Field
            label="Maximum quantity"
            min={1}
            onChange={(value) => updateEntry(index, "maximum_quantity", value)}
            type="number"
            value={entry.maximum_quantity}
          />
          <button
            aria-label={`Remove ${entry.item_id} loot entry`}
            className="studio-remove-button"
            onClick={() => onChange(entries.filter((_, entryIndex) => entryIndex !== index))}
            type="button"
          >
            ×
          </button>
        </div>
      ))}
      {entries.length === 0 && <p className="studio-hint">{emptyMessage}</p>}
      {items.length === 0 && <p className="studio-hint">Create an item or resource before adding a drop.</p>}
    </section>
  );
}

function QuestEditor({ quest, npcs, entities, currencies = [], dieSkins = [], locations, onChange }) {
  function set(field, value) {
    onChange((current, next) => { current[field] = next; }, value);
  }

  const objectiveTypes = [
    { id: "collect", name: "Collect item" },
    { id: "kill", name: "Defeat enemy" },
    { id: "talk", name: "Talk to NPC" },
    { id: "visit", name: "Visit location" },
  ];

  function targetsFor(type) {
    if (type === "visit") return locations;
    const validTypes = {
      collect: ITEM_RESOURCE_TYPES,
      kill: ["enemy"],
      talk: ["npc"],
    }[type] || [];
    return entities.filter((entity) => validTypes.includes(entity.type));
  }

  function createObjective(step) {
    const type = objectiveTypes.find((candidate) => targetsFor(candidate.id).length)?.id;
    const target = type ? targetsFor(type)[0] : null;
    if (!target) return null;
    const id = makeId("objective", new Set(step.objectives.map((objective) => objective.id)));
    return { id, type, target_id: target.id, quantity: 1 };
  }

  function updateStep(stepIndex, mutator) {
    onChange((current) => mutator(current.steps[stepIndex], current));
  }

  function removeStep(stepIndex) {
    onChange((current) => {
      const removedId = current.steps[stepIndex].id;
      const nextId = current.steps[stepIndex + 1]?.id || null;
      current.steps.splice(stepIndex, 1);
      for (const step of current.steps) {
        for (const choice of step.choices) {
          if (choice.next_step_id === removedId) choice.next_step_id = nextId;
        }
      }
      if (current.start_step_id === removedId) current.start_step_id = nextId || current.steps[0].id;
    });
  }

  return (
    <div className="studio-form">
      <div className="studio-detail-heading">
        <div><p className="eyebrow">QUEST / {quest.id}</p><h2>{quest.title}</h2></div>
        <span className="studio-kind-tag">QUEST</span>
      </div>
      <Field label="Quest title" value={quest.title} onChange={(value) => set("title", value)} />
      <TextAreaField label="Description shown to players" value={quest.description} onChange={(value) => set("description", value)} />
      <SelectField
        label="Quest giver"
        options={npcs}
        value={quest.giver_npc_id}
        onChange={(value) => set("giver_npc_id", value)}
      />
      <section className="studio-subsection studio-quest-steps">
        <div className="studio-subsection-heading">
          <div><h3>Quest steps</h3><p>Each step needs objectives and explicit player choices. Ending choices send the player back to the giver.</p></div>
          <button
            className="studio-small-button"
            disabled={quest.steps.length >= 100 || quest.steps[quest.steps.length - 1].choices.length >= 20}
            onClick={() => onChange((current) => {
              const stepId = makeId(`step_${current.steps.length + 1}`, new Set(current.steps.map((step) => step.id)));
              const step = {
                id: stepId,
                title: `Step ${current.steps.length + 1}`,
                description: "",
                objectives: [],
                choices: [{ id: "finish", text: "Return to the quest giver", next_step_id: null }],
              };
              const objective = createObjective(step);
              if (!objective) return;
              step.objectives.push(objective);
              const previous = current.steps[current.steps.length - 1];
              previous.choices.push({
                id: makeId("continue", new Set(previous.choices.map((choice) => choice.id))),
                text: `Continue to ${step.title}`,
                next_step_id: stepId,
              });
              current.steps.push(step);
            })}
            type="button"
          >
            Add step
          </button>
        </div>
        {quest.steps.map((step, stepIndex) => (
          <section className="studio-quest-step" key={step.id}>
            <div className="studio-subsection-heading">
              <h3>Step {stepIndex + 1}</h3>
              <button
                aria-label={`Remove step ${stepIndex + 1}`}
                className="studio-remove-button"
                disabled={quest.steps.length === 1}
                onClick={() => removeStep(stepIndex)}
                type="button"
              >
                ×
              </button>
            </div>
            <Field
              label="Step title"
              value={step.title}
              onChange={(value) => updateStep(stepIndex, (current) => { current.title = value; })}
            />
            <TextAreaField
              label="Step description"
              value={step.description}
              onChange={(value) => updateStep(stepIndex, (current) => { current.description = value; })}
              rows={2}
            />
            <div className="studio-subsection-heading">
              <div><h4>Objectives</h4><p>Collect checks inventory; defeated enemies, NPC conversations, and visits count as they happen.</p></div>
              <button
                className="studio-small-button"
                disabled={step.objectives.length >= 20}
                onClick={() => updateStep(stepIndex, (current) => {
                  const objective = createObjective(current);
                  if (objective) current.objectives.push(objective);
                })}
                type="button"
              >
                Add objective
              </button>
            </div>
            {step.objectives.map((objective, objectiveIndex) => {
              const targets = targetsFor(objective.type);
              return (
                <div className="studio-quest-objective" key={objective.id}>
                  <SelectField
                    label="Objective type"
                    options={objectiveTypes.filter((candidate) => targetsFor(candidate.id).length)}
                    value={objective.type}
                    onChange={(type) => updateStep(stepIndex, (current) => {
                      const target = targetsFor(type)[0];
                      current.objectives[objectiveIndex] = {
                        ...current.objectives[objectiveIndex],
                        type,
                        target_id: target?.id || "",
                        quantity: ["talk", "visit"].includes(type) ? 1 : current.objectives[objectiveIndex].quantity,
                      };
                    })}
                  />
                  <SelectField
                    label="Target"
                    options={targets}
                    value={objective.target_id}
                    onChange={(targetId) => updateStep(stepIndex, (current) => {
                      current.objectives[objectiveIndex].target_id = targetId;
                    })}
                  />
                  <Field
                    label="Count"
                    min={1}
                    onChange={(value) => updateStep(stepIndex, (current) => {
                      current.objectives[objectiveIndex].quantity = value;
                    })}
                    type="number"
                    value={objective.quantity}
                  />
                  <button
                    aria-label={`Remove objective ${objectiveIndex + 1} from step ${stepIndex + 1}`}
                    className="studio-remove-button"
                    disabled={step.objectives.length === 1}
                    onClick={() => updateStep(stepIndex, (current) => {
                      current.objectives.splice(objectiveIndex, 1);
                    })}
                    type="button"
                  >
                    ×
                  </button>
                </div>
              );
            })}
            <div className="studio-subsection-heading">
              <div><h4>Player choices</h4><p>Choices only appear after every objective in this step is complete.</p></div>
              <button
                className="studio-small-button"
                disabled={step.choices.length >= 20}
                onClick={() => updateStep(stepIndex, (current) => {
                  current.choices.push({
                    id: makeId("choice", new Set(current.choices.map((choice) => choice.id))),
                    text: "Return to the quest giver",
                    next_step_id: null,
                  });
                })}
                type="button"
              >
                Add choice
              </button>
            </div>
            {step.choices.map((choice, choiceIndex) => (
              <div className="studio-quest-choice" key={choice.id}>
                <Field
                  label="Choice text"
                  value={choice.text}
                  onChange={(value) => updateStep(stepIndex, (current) => {
                    current.choices[choiceIndex].text = value;
                  })}
                />
                <SelectField
                  emptyLabel="Complete quest"
                  label="Then go to"
                  options={quest.steps.slice(stepIndex + 1).map((targetStep) => ({
                    id: targetStep.id,
                    name: targetStep.title,
                  }))}
                  value={choice.next_step_id}
                  onChange={(nextStepId) => updateStep(stepIndex, (current) => {
                    current.choices[choiceIndex].next_step_id = nextStepId;
                  })}
                />
                <button
                  aria-label={`Remove choice ${choiceIndex + 1} from step ${stepIndex + 1}`}
                  className="studio-remove-button"
                  disabled={step.choices.length === 1}
                  onClick={() => updateStep(stepIndex, (current) => {
                    current.choices.splice(choiceIndex, 1);
                  })}
                  type="button"
                >
                  ×
                </button>
              </div>
            ))}
          </section>
        ))}
      </section>
      <Field
        label="Experience reward"
        min={0}
        onChange={(value) => set("reward_experience", value)}
        type="number"
        value={quest.reward_experience}
      />
      <section className="studio-subsection">
        <div className="studio-subsection-heading">
          <div><h3>Item rewards</h3><p>Players receive these when they return to the giver for final turn-in.</p></div>
          <button
            className="studio-small-button"
            disabled={(quest.reward_items || []).length >= 20 || !entities.some((entity) => ITEM_RESOURCE_TYPES.includes(entity.type))}
            onClick={() => onChange((current) => {
              const rewardItems = entities.filter((entity) => ITEM_RESOURCE_TYPES.includes(entity.type));
              if (!rewardItems.length) return;
              current.reward_items.push({ item_id: rewardItems[0].id, quantity: 1 });
            })}
            type="button"
          >
            Add reward
          </button>
        </div>
        {(quest.reward_items || []).map((reward, index) => (
          <div className="studio-quest-objective" key={`${reward.item_id}-${index}`}>
            <SelectField
              label="Reward item"
              options={entities.filter((entity) => ITEM_RESOURCE_TYPES.includes(entity.type))}
              value={reward.item_id}
              onChange={(itemId) => onChange((current) => { current.reward_items[index].item_id = itemId; })}
            />
            <Field
              label="Quantity"
              min={1}
              onChange={(value) => onChange((current) => { current.reward_items[index].quantity = value; })}
              type="number"
              value={reward.quantity}
            />
            <button
              aria-label={`Remove ${reward.item_id} quest reward`}
              className="studio-remove-button"
              onClick={() => onChange((current) => { current.reward_items.splice(index, 1); })}
              type="button"
            >
              ×
            </button>
          </div>
        ))}
      </section>
      <section className="studio-subsection">
        <div className="studio-subsection-heading">
          <div><h3>Currency rewards</h3><p>Currency added to the player's wallet at final turn-in.</p></div>
          <button
            className="studio-small-button"
            disabled={currencies.length === 0 || (quest.reward_currencies || []).length >= 20}
            onClick={() => onChange((current) => {
              current.reward_currencies ||= [];
              current.reward_currencies.push({ currency_id: currencies[0].id, amount: 1 });
            })}
            type="button"
          >
            Add currency reward
          </button>
        </div>
        {(quest.reward_currencies || []).map((reward, index) => (
          <div className="studio-quest-objective" key={`${reward.currency_id}-${index}`}>
            <SelectField
              label="Currency"
              options={currencies}
              value={reward.currency_id}
              onChange={(value) => onChange((current) => { current.reward_currencies[index].currency_id = value; })}
            />
            <Field
              label="Amount"
              min={1}
              onChange={(value) => onChange((current) => { current.reward_currencies[index].amount = value; })}
              type="number"
              value={reward.amount}
            />
            <button
              aria-label="Remove currency reward"
              className="studio-remove-button"
              onClick={() => onChange((current) => { current.reward_currencies.splice(index, 1); })}
              type="button"
            >
              ×
            </button>
          </div>
        ))}
        {currencies.length === 0 && <p className="studio-hint">Create a currency in the Currencies section first.</p>}
      </section>
      <section className="studio-subsection">
        <h3>Die skin rewards</h3>
        {dieSkins.map((skin) => (
          <label className="studio-field studio-inline-check" key={skin.id}>
            <span>{skin.name}</span>
            <input
              checked={(quest.reward_die_skin_ids || []).includes(skin.id)}
              onChange={(event) => onChange((current) => {
                const ids = new Set(current.reward_die_skin_ids || []);
                if (event.target.checked) ids.add(skin.id); else ids.delete(skin.id);
                current.reward_die_skin_ids = [...ids];
              })}
              type="checkbox"
            />
          </label>
        ))}
        {dieSkins.length === 0 && <p className="studio-hint">Create a skin in the Die skins section first.</p>}
      </section>
      <p className="studio-hint">To gate a passage, select this quest as the exit requirement in the destination location's editor.</p>
    </div>
  );
}

const ENCHANTMENT_EFFECT_DEFAULTS = {
  stat_modifier: { type: "stat_modifier", stat: "attack", mode: "flat", amount: 1 },
  luck: { type: "luck", drop_chance_bonus_percent: 10, gathering_yield_bonus_percent: 0 },
  quest_path: { type: "quest_path" },
  damage_over_time: { type: "damage_over_time", amount: 1, interval_seconds: 15 },
  life_steal: { type: "life_steal", percent: 10 },
  thorns: { type: "thorns", amount: 1 },
  cursed_binding: { type: "cursed_binding" },
};

function EnchantmentEditor({ enchantment, onChange }) {
  const effects = enchantment.effects || [];
  function updateEffect(index, field, value) {
    onChange("effects", effects.map((effect, i) => (i === index ? { ...effect, [field]: value } : effect)));
  }
  return (
    <div className="studio-form">
      <div className="studio-form-heading"><p className="eyebrow">ENCHANTMENT</p><h2>{enchantment.name}</h2></div>
      <Field label="Name" onChange={(value) => onChange("name", value)} value={enchantment.name} />
      <TextAreaField label="Description" onChange={(value) => onChange("description", value)} rows={3} value={enchantment.description || ""} />
      <SelectField
        label="Kind"
        options={[{ id: "enchantment", name: "Enchantment (beneficial)" }, { id: "curse", name: "Curse (harmful)" }]}
        value={enchantment.kind}
        onChange={(value) => onChange("kind", value)}
      />
      <section className="studio-subsection">
        <div className="studio-subsection-heading">
          <div><h3>Effects</h3><p>Negative amounts make penalties. Damage over time never kills; it stops at 1 health.</p></div>
          <button
            className="studio-small-button"
            disabled={effects.length >= 20}
            onClick={() => onChange("effects", [...effects, { ...ENCHANTMENT_EFFECT_DEFAULTS.stat_modifier }])}
            type="button"
          >
            Add effect
          </button>
        </div>
        {effects.map((effect, index) => (
          <section className="studio-effect-card" key={`${effect.type}-${index}`}>
            <div className="studio-subsection-heading">
              <strong>Effect {index + 1}</strong>
              <button
                aria-label={`Remove effect ${index + 1}`}
                className="studio-remove-button"
                disabled={effects.length <= 1}
                onClick={() => onChange("effects", effects.filter((_, i) => i !== index))}
                type="button"
              >
                ×
              </button>
            </div>
            <SelectField
              label="Effect type"
              options={[
                { id: "stat_modifier", name: "Change a stat" },
                { id: "luck", name: "Luck (drops / gathering)" },
                { id: "quest_path", name: "Highlight path to active quest" },
                { id: "damage_over_time", name: "Damage over time" },
                { id: "life_steal", name: "Life steal" },
                { id: "thorns", name: "Thorns" },
                { id: "cursed_binding", name: "Cannot be unequipped" },
              ]}
              value={effect.type}
              onChange={(type) => onChange("effects", effects.map((current, i) => (i === index ? { ...ENCHANTMENT_EFFECT_DEFAULTS[type] } : current)))}
            />
            {effect.type === "stat_modifier" && (
              <div className="studio-two-fields">
                <SelectField
                  label="Stat"
                  options={["attack", "defense", "speed", "max_health"].map((id) => ({ id, name: id.replace("_", " ") }))}
                  value={effect.stat}
                  onChange={(value) => updateEffect(index, "stat", value)}
                />
                <SelectField
                  label="Mode"
                  options={[{ id: "flat", name: "Flat" }, { id: "percent", name: "Percent" }]}
                  value={effect.mode}
                  onChange={(value) => updateEffect(index, "mode", value)}
                />
                <Field label="Amount (negative for a penalty)" max={500} min={-500} onChange={(value) => updateEffect(index, "amount", value)} type="number" value={effect.amount} />
              </div>
            )}
            {effect.type === "luck" && (
              <div className="studio-two-fields">
                <Field label="Drop chance bonus (%)" max={1000} min={0} onChange={(value) => updateEffect(index, "drop_chance_bonus_percent", value)} type="number" value={effect.drop_chance_bonus_percent} />
                <Field label="Gathering yield bonus (%)" max={1000} min={0} onChange={(value) => updateEffect(index, "gathering_yield_bonus_percent", value)} type="number" value={effect.gathering_yield_bonus_percent} />
              </div>
            )}
            {effect.type === "damage_over_time" && (
              <div className="studio-two-fields">
                <Field label="Damage per tick" max={1000} min={1} onChange={(value) => updateEffect(index, "amount", value)} type="number" value={effect.amount} />
                <Field label="Seconds between ticks" max={3600} min={5} onChange={(value) => updateEffect(index, "interval_seconds", value)} type="number" value={effect.interval_seconds} />
              </div>
            )}
            {effect.type === "life_steal" && (
              <Field label="Percent of damage dealt returned as health" max={100} min={1} onChange={(value) => updateEffect(index, "percent", value)} type="number" value={effect.percent} />
            )}
            {effect.type === "thorns" && (
              <Field label="Damage reflected when hit" max={1000} min={1} onChange={(value) => updateEffect(index, "amount", value)} type="number" value={effect.amount} />
            )}
            {effect.type === "quest_path" && <p className="studio-hint">Shows the route to the active quest objective on the world map and highlights the next exit.</p>}
            {effect.type === "cursed_binding" && <p className="studio-hint">The equipped item cannot be removed or replaced.</p>}
          </section>
        ))}
      </section>
    </div>
  );
}

function DieSkinEditor({ skin, onChange, onGive }) {
  const colorField = (label, field, optional = false) => (
    <label className="studio-field">
      <span>{label}</span>
      <span className="studio-color-row">
        <input
          onChange={(event) => onChange(field, event.target.value)}
          type="color"
          value={skin[field] || "#000000"}
        />
        {optional && (
          <button className="studio-secondary-button" onClick={() => onChange(field, null)} type="button">
            {skin[field] ? "Remove" : "None"}
          </button>
        )}
      </span>
    </label>
  );
  return (
    <div className="studio-form">
      <div className="studio-form-heading"><p className="eyebrow">DIE SKIN</p><h2>{skin.name}</h2></div>
      <Field label="Name" onChange={(value) => onChange("name", value)} value={skin.name} />
      <TextAreaField label="Description" onChange={(value) => onChange("description", value)} rows={3} value={skin.description || ""} />
      {colorField("Face color", "face_color")}
      {colorField("Edge color", "edge_color")}
      {colorField("Number color", "number_color")}
      {colorField("Glow color (optional)", "glow_color", true)}
      <SelectField label="Particle effect" options={PARTICLE_EFFECTS} value={skin.particle_effect} onChange={(value) => onChange("particle_effect", value || "none")} />
      {colorField("Particle color", "particle_color")}
      <p className="studio-hint">Preview</p>
      <DiePreview skin={skin} />
      <button className="studio-secondary-button" onClick={onGive} type="button">Give to me</button>
      <p className="studio-hint">Players unlock skins from quest rewards (set them in the Quests tab) and pick the active one from the Dice button.</p>
    </div>
  );
}

function CurrencyEditor({ currency, onChange }) {
  return (
    <div className="studio-form">
      <div className="studio-form-heading"><p className="eyebrow">CURRENCY</p><h2>{currency.name}</h2></div>
      <Field label="Name" onChange={(value) => onChange("name", value)} value={currency.name} />
      <Field label="Symbol (shown next to amounts, e.g. g or $)" onChange={(value) => onChange("symbol", value.slice(0, 8))} value={currency.symbol || ""} />
      <TextAreaField label="Description" onChange={(value) => onChange("description", value)} rows={3} value={currency.description || ""} />
      <p className="studio-hint">Players earn this from enemy drops and quest rewards, and spend it at NPC shops. Wallets start empty.</p>
    </div>
  );
}

function CurrencyDropEditor({ entries, currencies, onChange }) {
  function update(index, field, value) {
    onChange(entries.map((entry, entryIndex) => (entryIndex === index ? { ...entry, [field]: value } : entry)));
  }
  return (
    <section className="studio-subsection">
      <div className="studio-subsection-heading">
        <div><h3>Currency drops</h3><p>Currency added to the wallet of the player who defeats this enemy.</p></div>
        <button
          className="studio-small-button"
          disabled={currencies.length === 0 || entries.length >= 20}
          onClick={() => onChange([...entries, { currency_id: currencies[0].id, chance: 1, minimum_amount: 1, maximum_amount: 1 }])}
          type="button"
        >
          Add currency drop
        </button>
      </div>
      {entries.map((entry, index) => (
        <div className="studio-loot-row" key={`${entry.currency_id}-${index}`}>
          <SelectField label="Currency" options={currencies} value={entry.currency_id} onChange={(value) => update(index, "currency_id", value)} />
          <Field label="Chance (%)" max={100} min={0} onChange={(value) => update(index, "chance", value / 100)} step={0.1} type="number" value={Number((entry.chance * 100).toFixed(1))} />
          <Field label="Minimum amount" min={1} onChange={(value) => update(index, "minimum_amount", value)} type="number" value={entry.minimum_amount} />
          <Field label="Maximum amount" min={1} onChange={(value) => update(index, "maximum_amount", value)} type="number" value={entry.maximum_amount} />
          <button aria-label="Remove currency drop" className="studio-remove-button" onClick={() => onChange(entries.filter((_, entryIndex) => entryIndex !== index))} type="button">×</button>
        </div>
      ))}
      {entries.length === 0 && <p className="studio-hint">This enemy does not drop currency.</p>}
      {currencies.length === 0 && <p className="studio-hint">Create a currency in the Currencies section first.</p>}
    </section>
  );
}

function DialogueEditor({ dialogue, onChange }) {
  const nodes = dialogue?.nodes || [];

  function update(mutator) {
    const next = structuredClone(dialogue || { start_node_id: null, nodes: [] });
    mutator(next);
    onChange(next);
  }

  function addNode() {
    const id = makeId("dialogue_node", new Set(nodes.map((node) => node.id)));
    update((next) => {
      next.nodes.push({ id, title: "New dialogue node", text: "Write what the NPC says here.", choices: [] });
      if (!next.start_node_id) next.start_node_id = id;
    });
  }

  function deleteNode(nodeId) {
    update((next) => {
      next.nodes = next.nodes.filter((node) => node.id !== nodeId);
      for (const node of next.nodes) {
        node.choices = node.choices.filter((choice) => choice.next_node_id !== nodeId);
      }
      if (next.start_node_id === nodeId) next.start_node_id = next.nodes[0]?.id || null;
    });
  }

  return (
    <section className="studio-subsection studio-dialogue-editor">
      <div className="studio-subsection-heading">
        <div><h3>Branching dialogue</h3><p>Each conversation starts at the opening node. A node with no choices ends the conversation.</p></div>
        <button className="studio-small-button" disabled={nodes.length >= 100} onClick={addNode} type="button">Add node</button>
      </div>
      {nodes.length === 0 ? (
        <p className="studio-hint">No dialogue yet. Add a node to write the NPC's opening line.</p>
      ) : (
        <>
          <SelectField
            label="Opening node"
            options={nodes.map((node) => ({ id: node.id, name: node.title }))}
            value={dialogue.start_node_id}
            onChange={(value) => update((next) => { next.start_node_id = value; })}
          />
          {nodes.map((node, index) => (
            <section className="studio-dialogue-node" key={node.id}>
              <div className="studio-subsection-heading">
                <span className="studio-kind-tag">NODE {index + 1}</span>
                <button aria-label={`Delete dialogue node ${node.title}`} className="studio-remove-button" onClick={() => deleteNode(node.id)} type="button">×</button>
              </div>
              <Field label="Node title" value={node.title} onChange={(value) => update((next) => {
                next.nodes.find((entry) => entry.id === node.id).title = value;
              })} />
              <TextAreaField label="NPC dialogue" value={node.text} onChange={(value) => update((next) => {
                next.nodes.find((entry) => entry.id === node.id).text = value;
              })} />
              <div className="studio-subsection-heading">
                <div><h4>Player choices</h4><p>Each choice leads to another dialogue node.</p></div>
                <button className="studio-small-button" disabled={node.choices.length >= 12} onClick={() => update((next) => {
                  const targetId = next.nodes[0].id;
                  const current = next.nodes.find((entry) => entry.id === node.id);
                  const choiceId = makeId("choice", new Set(current.choices.map((choice) => choice.id)));
                  current.choices.push({ id: choiceId, text: "Continue", next_node_id: targetId });
                })} type="button">Add choice</button>
              </div>
              {node.choices.map((choice) => (
                <div className="studio-dialogue-choice" key={choice.id}>
                  <Field label="Choice text" value={choice.text} onChange={(value) => update((next) => {
                    next.nodes.find((entry) => entry.id === node.id).choices.find((entry) => entry.id === choice.id).text = value;
                  })} />
                  <SelectField
                    label="Continue at"
                    options={nodes.map((entry) => ({ id: entry.id, name: entry.title }))}
                    value={choice.next_node_id}
                    onChange={(value) => update((next) => {
                      next.nodes.find((entry) => entry.id === node.id).choices.find((entry) => entry.id === choice.id).next_node_id = value;
                    })}
                  />
                  <button aria-label={`Delete choice ${choice.text}`} className="studio-remove-button" onClick={() => update((next) => {
                    next.nodes.find((entry) => entry.id === node.id).choices = next.nodes.find((entry) => entry.id === node.id).choices.filter((entry) => entry.id !== choice.id);
                  })} type="button">×</button>
                </div>
              ))}
              {node.choices.length === 0 && <p className="studio-hint">No choices: this node ends the conversation.</p>}
            </section>
          ))}
        </>
      )}
    </section>
  );
}

function RecipeEditor({ recipe, outputs, ingredients, stations, onChange }) {
  function set(field, value) {
    onChange((current, next) => { current[field] = next; }, value);
  }

  return (
    <div className="studio-form">
      <div className="studio-detail-heading">
        <div><p className="eyebrow">CRAFTING RECIPE / {recipe.id}</p><h2>{recipe.name}</h2></div>
        <span className="studio-kind-tag">RECIPE</span>
      </div>
      <Field label="Recipe name" value={recipe.name} onChange={(value) => set("name", value)} />
      <div className="studio-two-fields">
        <SelectField label="Crafted item" options={outputs} value={recipe.output_item_id} onChange={(value) => set("output_item_id", value)} />
        <Field label="Output quantity" min={1} onChange={(value) => set("output_quantity", value)} type="number" value={recipe.output_quantity} />
      </div>
      <section className="studio-subsection">
        <div className="studio-subsection-heading"><div><h3>Ingredients</h3><p>Items required to craft the output.</p></div><button className="studio-small-button" disabled={ingredients.length === 0} onClick={() => onChange((current) => {
          current.ingredients.push({ item_id: ingredients[0].id, quantity: 1 });
        })} type="button">Add ingredient</button></div>
        {recipe.ingredients.map((ingredient, index) => (
          <div className="studio-ingredient-row" key={`${ingredient.item_id}-${index}`}>
            <SelectField label="Ingredient" options={ingredients} value={ingredient.item_id} onChange={(value) => onChange((current, next) => { current.ingredients[index].item_id = next; }, value)} />
            <Field label="Quantity" min={1} onChange={(value) => onChange((current, next) => { current.ingredients[index].quantity = next; }, value)} type="number" value={ingredient.quantity} />
            <button aria-label="Remove ingredient" className="studio-remove-button" disabled={recipe.ingredients.length === 1} onClick={() => onChange((current) => { current.ingredients.splice(index, 1); })} type="button">×</button>
          </div>
        ))}
      </section>
      <SelectField label="Crafting station" emptyLabel="No station required" options={stations} value={recipe.station_id} onChange={(value) => set("station_id", value)} />
      <div className="studio-two-fields">
        <SelectField label="Required skill" emptyLabel="No skill requirement" options={SKILL_OPTIONS} value={recipe.skill} onChange={(value) => set("skill", value || "")} />
        <Field label="Skill level" min={0} onChange={(value) => set("skill_level", value)} type="number" value={recipe.skill_level} />
      </div>
    </div>
  );
}
