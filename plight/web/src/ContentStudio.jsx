import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";

const NAVIGATION = [
  ["map", "World map"],
  ["locations", "Locations"],
  ["enemies", "Enemies"],
  ["npcs", "NPCs"],
  ["items", "Items"],
  ["weapons", "Weapons"],
  ["recipes", "Recipes"],
  ["environment", "Furniture / objects"],
  ["resources", "Resources"],
];

const ENTITY_TABS = {
  enemies: ["enemy", { health: 20, attack: 3, defense: 1, speed: 10 }],
  npcs: ["npc", { health: 100 }],
  items: ["item", { weight: 1, stack_size: 99, value: 1 }],
  weapons: ["weapon", { damage: 5, speed: 10, stamina_cost: 1, value: 10 }],
  environment: ["furniture", { durability: 100 }],
  resources: ["resource", { yield: 1, respawn_minutes: 60 }],
};

const CATEGORY_NAMES = {
  enemy: "Enemies",
  npc: "NPCs",
  item: "Items",
  weapon: "Weapons",
  furniture: "Furniture",
  object: "Objects",
  resource: "Resources",
};

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
  const locationsById = new Map(locations.map((location) => [location.id, location]));
  const links = locations.flatMap((location) =>
    Object.entries(location.exits).map(([direction, destinationId]) => ({
      id: `${location.id}-${direction}-${destinationId}`,
      from: location,
      to: locationsById.get(destinationId),
      direction,
    })).filter((link) => link.to),
  );

  return (
    <svg aria-label="Map of connected world locations" className="studio-map" role="img" viewBox="0 0 1000 620">
      <defs>
        <marker id="map-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="6" refY="3" viewBox="0 0 6 6">
          <path d="M0,0 L6,3 L0,6" fill="none" stroke="#c78248" strokeWidth="1.2" />
        </marker>
      </defs>
      <g className="studio-map-grid">
        {Array.from({ length: 9 }, (_, index) => <path d={`M${index * 125 + 62} 0 V620`} key={`v${index}`} />)}
        {Array.from({ length: 5 }, (_, index) => <path d={`M0 ${index * 125 + 60} H1000`} key={`h${index}`} />)}
      </g>
      {links.map((link) => {
        const x1 = link.from.position.x * 10;
        const y1 = link.from.position.y * 6;
        const x2 = link.to.position.x * 10;
        const y2 = link.to.position.y * 6;
        const midpointX = (x1 + x2) / 2;
        const midpointY = (y1 + y2) / 2;
        return (
          <g className="studio-map-link" key={link.id}>
            <line markerEnd="url(#map-arrow)" x1={x1} x2={x2} y1={y1} y2={y2} />
            <text x={midpointX} y={midpointY - 9}>{link.direction}</text>
          </g>
        );
      })}
      {locations.map((location) => {
        const x = location.position.x * 10;
        const y = location.position.y * 6;
        const selected = location.id === content.selectedLocationId;
        const kinds = [
          location.enemy_ids.length && `${location.enemy_ids.length} enemy`,
          location.npc_ids.length && `${location.npc_ids.length} NPC`,
        ].filter(Boolean).join(" / ");
        return (
          <g
            aria-label={`${location.name}, ${location.exits && Object.keys(location.exits).length} exits`}
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
            <rect height="76" rx="4" width="176" x="-88" y="-38" />
            <text className="studio-map-node-name" y="-4">{location.name}</text>
            <text className="studio-map-node-meta" y="17">{kinds || "Quiet location"}</text>
            <text className="studio-map-coordinate" y="31">{location.position.x}, {location.position.y}</text>
          </g>
        );
      })}
      {locations.length === 0 && <text className="studio-map-empty" x="500" y="310">Create a location to start your map.</text>}
    </svg>
  );
}

export default function ContentStudio({ token, onClose, onSignOut }) {
  const [content, setContent] = useState(null);
  const [revision, setRevision] = useState("");
  const [tab, setTab] = useState("map");
  const [selectedId, setSelectedId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [linkForm, setLinkForm] = useState({ from: "", to: "", direction: "east" });

  async function loadContent() {
    setError("");
    setBusy(true);
    try {
      const result = await api("/api/v1/content", { token });
      setContent(result.content);
      setRevision(result.revision);
      setSelectedId(result.content.locations[0]?.id || "");
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
  const currentLocation = content?.locations.find((location) => location.id === selectedId);
  const currentRecipe = recipes.find((recipe) => recipe.id === selectedId);
  const currentEntity = (content?.entities || []).find((entity) => entity.id === selectedId);
  const visibleEntities = useMemo(() => {
    if (!content) return [];
    if (tab === "environment") return content.entities.filter((entity) => ["furniture", "object"].includes(entity.type));
    const entityType = ENTITY_TABS[tab]?.[0];
    return entityType ? content.entities.filter((entity) => entity.type === entityType) : [];
  }, [content, tab]);

  function updateContent(mutator) {
    setContent((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      mutator(next);
      return next;
    });
    setNotice("");
  }

  function changeTab(nextTab) {
    setTab(nextTab);
    const nextList = nextTab === "locations"
      ? content.locations
      : nextTab === "recipes"
        ? content.recipes
        : (content.entities || []).filter((entity) =>
          nextTab === "environment"
            ? ["furniture", "object"].includes(entity.type)
            : entity.type === ENTITY_TABS[nextTab]?.[0],
        );
    setSelectedId(nextList[0]?.id || "");
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
          starting_species: [],
          exits: {},
          ambience: [],
          enemy_ids: [],
          npc_ids: [],
          object_ids: [],
          resource_ids: [],
        });
      });
      setSelectedId(id);
      return;
    }
    if (tab === "recipes") {
      const product = content.entities.find((entity) => ["item", "weapon"].includes(entity.type));
      const ingredient = content.entities.find((entity) => ["item", "weapon", "resource"].includes(entity.type));
      if (!product || !ingredient) {
        setError("Create at least one item or weapon and one ingredient before adding a recipe.");
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
        ...(type === "enemy" ? { attack_die_sides: 2 } : {}),
        ...(type === "npc" ? {
          race: "human",
          present_for: ["human", "goblin"],
          dialogue: { start_node_id: null, nodes: [] },
        } : {}),
        ambience: [],
        stock: [],
        weapon_ids: [],
      });
    });
    setSelectedId(id);
  }

  function deleteEntry() {
    const name = currentLocation?.name || currentRecipe?.name || currentEntity?.name;
    if (!name || !window.confirm(`Delete "${name}"? References to this content will be removed.`)) return;
    updateContent((next) => {
      if (tab === "locations") {
        next.locations = next.locations.filter((location) => location.id !== selectedId);
        for (const location of next.locations) {
          for (const [direction, destination] of Object.entries(location.exits)) {
            if (destination === selectedId) delete location.exits[direction];
          }
        }
      } else if (tab === "recipes") {
        next.recipes = next.recipes.filter((recipe) => recipe.id !== selectedId);
      } else {
        const removed = entitiesById.get(selectedId);
        next.entities = next.entities.filter((entity) => entity.id !== selectedId);
        for (const location of next.locations) {
          for (const key of ["enemy_ids", "npc_ids", "object_ids", "resource_ids"]) {
            location[key] = location[key].filter((entityId) => entityId !== selectedId);
          }
        }
        for (const entity of next.entities) {
          entity.stock = entity.stock.filter((entry) => entry.item_id !== selectedId);
          entity.weapon_ids = entity.weapon_ids.filter((weaponId) => weaponId !== selectedId);
        }
        next.recipes = next.recipes.filter((recipe) =>
          recipe.output_item_id !== selectedId && recipe.station_id !== selectedId,
        );
        for (const recipe of next.recipes) {
          recipe.ingredients = recipe.ingredients.filter((entry) => entry.item_id !== selectedId);
        }
        next.recipes = next.recipes.filter((recipe) => recipe.ingredients.length > 0);
        if (removed?.type === "item" || removed?.type === "weapon" || removed?.type === "resource") {
          for (const entity of next.entities) {
            entity.stock = entity.stock.filter((entry) => entry.item_id !== selectedId);
          }
        }
      }
    });
    setSelectedId("");
  }

  async function saveContent() {
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
  const eligibleItems = (content?.entities || []).filter((entity) => ["item", "weapon", "resource"].includes(entity.type));
  const eligibleOutputs = (content?.entities || []).filter((entity) => ["item", "weapon"].includes(entity.type));
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
          <button className="studio-secondary-button" disabled={busy} onClick={loadContent} type="button">Reload</button>
          <button className="primary-button" disabled={busy || !content} onClick={saveContent} type="button">{busy ? "Saving…" : "Save to active world"}</button>
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
                <small>{id === "map" ? content.locations.length : id === "locations" ? content.locations.length : id === "recipes" ? content.recipes.length : visibleCount(content, id)}</small>
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
                  <WorldMap content={{ ...content, selectedLocationId: selectedId }} onSelect={(id) => { setSelectedId(id); setTab("locations"); }} />
                </div>
                <div className="studio-map-controls">
                  <p>Connections create matching exits in both locations. Select nodes to edit them; their map position can be adjusted in location details.</p>
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
                    <div><p className="eyebrow">{tab === "locations" ? "WORLD AREAS" : tab === "recipes" ? "CRAFTING" : "CATALOG"}</p><h2>{NAVIGATION.find(([id]) => id === tab)?.[1]}</h2></div>
                    {tab !== "locations" || content.locations.length > 0 ? (
                      <button aria-label={`Create ${tab === "locations" ? "location" : tab === "recipes" ? "recipe" : "entity"}`} className="studio-add-button" onClick={createEntry} type="button">+</button>
                    ) : null}
                  </div>
                  <div className="studio-entry-list">
                    {(tab === "locations" ? content.locations : tab === "recipes" ? recipes : visibleEntities).map((entry) => (
                      <button className={`studio-entry ${selectedId === entry.id ? "selected" : ""}`} key={entry.id} onClick={() => setSelectedId(entry.id)} type="button">
                        <span>{entry.name}</span>
                        <small>{entry.id}</small>
                      </button>
                    ))}
                    {(tab === "locations" ? content.locations : tab === "recipes" ? recipes : visibleEntities).length === 0 && <p className="studio-empty">Nothing here yet. Use + to create one.</p>}
                  </div>
                  {(currentLocation || currentRecipe || currentEntity) && (
                    <button className="studio-delete-button" onClick={deleteEntry} type="button">Delete selected</button>
                  )}
                </aside>
                <div className="studio-detail-pane">
                  {currentLocation && tab === "locations" && (
                    <LocationEditor
                      location={currentLocation}
                      entitiesById={entitiesById}
                      locations={content.locations}
                      onChange={updateLocation}
                    />
                  )}
                  {currentEntity && ["enemies", "npcs", "items", "weapons", "environment", "resources"].includes(tab) && (
                    <EntityEditor
                      entity={currentEntity}
                      locations={content.locations}
                      entities={content.entities}
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
                  {!currentLocation && !currentEntity && !currentRecipe && <div className="studio-empty-detail">Select an entry or create a new one.</div>}
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

function LocationEditor({ location, entitiesById, locations, onChange }) {
  function change(field, value) {
    onChange((current, nextValue) => { current[field] = nextValue; }, value);
  }

  function toggleId(field, id, selected) {
    onChange((current) => {
      current[field] = selected
        ? [...current[field], id]
        : current[field].filter((value) => value !== id);
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
        <h3>Map position</h3>
        <p>Move this location around on the map using its coordinates.</p>
        <div className="studio-two-fields">
          <Field label="Horizontal (0–100)" max={100} min={0} onChange={(value) => onChange((current) => { current.position.x = value; })} type="number" value={location.position.x} />
          <Field label="Vertical (0–100)" max={100} min={0} onChange={(value) => onChange((current) => { current.position.y = value; })} type="number" value={location.position.y} />
        </div>
      </section>
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
      </section>
      <section className="studio-subsection">
        <h3>Location population</h3>
        <p>Choose which authored content appears here.</p>
        <EntityPicker title="Enemies" options={[...entitiesById.values()].filter((entity) => entity.type === "enemy")} selected={location.enemy_ids} onToggle={(id, selected) => toggleId("enemy_ids", id, selected)} />
        <EntityPicker title="NPCs" options={[...entitiesById.values()].filter((entity) => entity.type === "npc")} selected={location.npc_ids} onToggle={(id, selected) => toggleId("npc_ids", id, selected)} />
        <EntityPicker title="Furniture and objects" options={[...entitiesById.values()].filter((entity) => ["furniture", "object"].includes(entity.type))} selected={location.object_ids} onToggle={(id, selected) => toggleId("object_ids", id, selected)} />
        <EntityPicker title="Gatherable resources" options={[...entitiesById.values()].filter((entity) => entity.type === "resource")} selected={location.resource_ids} onToggle={(id, selected) => toggleId("resource_ids", id, selected)} />
        {(enemies.length > 0 || npcs.length > 0) && <p className="studio-hint">This area currently contains {[...enemies, ...npcs].join(", ")}.</p>}
      </section>
    </div>
  );
}

function EntityEditor({ entity, entities, locations, onChange, onLocationToggle }) {
  const relationField = {
    enemy: "enemy_ids",
    npc: "npc_ids",
    furniture: "object_ids",
    object: "object_ids",
    resource: "resource_ids",
  }[entity.type];
  const stockOptions = entities.filter((item) => ["item", "weapon", "resource"].includes(item.type));
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
        <SelectField
          label="Environment object type"
          options={[{ id: "furniture", name: "Furniture" }, { id: "object", name: "Other object" }]}
          value={entity.type}
          onChange={(value) => set("type", value)}
        />
      )}
      <Field label="Name" value={entity.name} onChange={(value) => set("name", value)} />
      <TextAreaField label="Description" value={entity.description} onChange={(value) => set("description", value)} />
      {entity.type === "npc" && (
        <>
          <SelectField
            label="NPC race"
            options={[{ id: "human", name: "Human" }, { id: "goblin", name: "Goblin" }]}
            value={entity.race}
            onChange={(value) => set("race", value)}
          />
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
          <Field
            label="Attack die (number of sides)"
            min={2}
            max={100}
            onChange={(value) => set("attack_die_sides", value)}
            type="number"
            value={entity.attack_die_sides ?? 2}
          />
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
          <EntityPicker title="Equipped weapons" options={weaponOptions} selected={entity.weapon_ids} onToggle={(id, selected) => set("weapon_ids", selected ? [...entity.weapon_ids, id] : entity.weapon_ids.filter((weaponId) => weaponId !== id))} emptyMessage="Create a weapon to equip one." />
          <section className="studio-subsection">
            <div className="studio-subsection-heading"><div><h3>Shop stock</h3><p>Items this NPC offers for sale.</p></div><button className="studio-small-button" disabled={stockOptions.length === 0} onClick={() => onChange((current) => {
              current.stock.push({ item_id: stockOptions[0].id, quantity: 1, price: 1 });
            })} type="button">Add stock</button></div>
            {entity.stock.map((entry, index) => (
              <div className="studio-stock-row" key={`${entry.item_id}-${index}`}>
                <SelectField label="Item" options={stockOptions} value={entry.item_id} onChange={(value) => setStock(index, "item_id", value)} />
                <Field label="Quantity" min={0} onChange={(value) => setStock(index, "quantity", value)} type="number" value={entry.quantity} />
                <Field label="Price" min={0} onChange={(value) => setStock(index, "price", value)} type="number" value={entry.price} />
                <button aria-label="Remove stock item" className="studio-remove-button" onClick={() => onChange((current) => { current.stock.splice(index, 1); })} type="button">×</button>
              </div>
            ))}
            {entity.stock.length === 0 && <p className="studio-hint">This NPC is not selling anything.</p>}
          </section>
        </>
      )}
    </div>
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
        <Field label="Required skill" onChange={(value) => set("skill", value)} value={recipe.skill} />
        <Field label="Skill level" min={0} onChange={(value) => set("skill_level", value)} type="number" value={recipe.skill_level} />
      </div>
    </div>
  );
}
