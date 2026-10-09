import { useEffect, useState } from "react";

export const SPELL_ANIMATIONS = ["bolt", "beam", "burst", "nova", "ring", "aura", "rain", "spiral"];

export function SpellEffectsOverlay({ casts, onDone }) {
  useEffect(() => {
    if (!casts?.length) return undefined;
    const timer = setTimeout(onDone, 1800);
    return () => clearTimeout(timer);
  }, [casts, onDone]);
  if (!casts?.length) return null;
  return (
    <div className="spell-overlay" aria-hidden="true">
      {casts.map((cast, index) => <SpellVisual key={`${cast.spell_id}-${index}`} visual={cast.visual} delay={index * 350} />)}
    </div>
  );
}

export function SpellVisual({ visual, delay = 0, loop = false }) {
  const { animation = "bolt", color = "#8f7cff", secondary_color: secondary, intensity = 1, particle_effect: particle } = visual || {};
  const style = {
    "--spell-color": color,
    "--spell-color-2": secondary || color,
    "--spell-scale": 0.8 + intensity * 0.4,
    animationDelay: `${delay}ms`,
    animationIterationCount: loop ? "infinite" : 1,
  };
  const count = 6 + intensity * 4;
  return (
    <div className={`spell-visual spell-${animation}`} style={style}>
      <span className="spell-core" />
      {Array.from({ length: particle && particle !== "none" ? count : 0 }, (_, index) => (
        <i
          className={`spell-particle spell-particle-${particle}`}
          key={index}
          style={{ "--i": index, "--n": count, animationDelay: `${delay + index * 60}ms`, animationIterationCount: loop ? "infinite" : 1 }}
        />
      ))}
    </div>
  );
}

export function SpellsDialog({ busy, enemies, magic, onCast, onClose }) {
  const [target, setTarget] = useState("");
  useEffect(() => {
    if (!enemies.some((enemy) => enemy.name === target)) setTarget(enemies[0]?.name || "");
  }, [enemies, target]);
  const book = magic?.spellbook;
  const percent = magic?.max_mana ? Math.round((magic.mana / magic.max_mana) * 100) : 0;
  function cast(spell) {
    onCast(spell.target === "enemy" ? `cast ${spell.name} at ${target}` : `cast ${spell.name}`);
  }
  return (
    <div className="dialog-backdrop" role="presentation">
      <section aria-label="Spells" aria-modal="true" className="spells-dialog" role="dialog">
        <header className="dialog-header">
          <h2>Spells</h2>
          <button onClick={onClose} type="button">Close</button>
        </header>
        <div className="mana-bar" title={`${magic?.regen_per_second ?? 0} mana per second`}>
          <div style={{ width: `${percent}%` }} />
          <span>Mana {magic?.mana ?? 0} / {magic?.max_mana ?? 0}</span>
        </div>
        {enemies.length > 0 && (
          <label className="spell-target">
            Target
            <select onChange={(event) => setTarget(event.target.value)} value={target}>
              {enemies.map((enemy) => <option key={enemy.id || enemy.name} value={enemy.name}>{enemy.name}</option>)}
            </select>
          </label>
        )}
        <h3>{book ? book.name : "Spellbook"}</h3>
        {!book && <p className="inventory-empty">Equip a spellbook in the Equipment tab to cast spells.</p>}
        <div className="spell-slots">
          {(book?.slots || []).map((slot) => (
            <article className="spell-card" key={slot.index} style={{ "--school-color": slot.spell?.school_color || "#555" }}>
              <small>{slot.label}{slot.school_id ? ` · ${slot.school_id}` : ""}{slot.max_level ? ` · max level ${slot.max_level}` : ""}</small>
              {slot.spell ? (
                <>
                  <strong>{slot.spell.name}</strong>
                  <span>{slot.spell.school_name} / {slot.spell.specialty_name} · level {slot.spell.required_level} · {slot.spell.mana_cost} mana</span>
                  {slot.spell.description && <p>{slot.spell.description}</p>}
                  <ul>{slot.spell.effects.map((effect) => <li key={effect}>{effect}</li>)}</ul>
                  {slot.spell.blocker && <em>{slot.spell.blocker}</em>}
                  <button disabled={busy || !slot.spell.castable || (slot.spell.target === "enemy" && !target)} onClick={() => cast(slot.spell)} type="button">Cast</button>
                </>
              ) : <span>Empty</span>}
            </article>
          ))}
        </div>
        <h3>Schools</h3>
        {(magic?.schools || []).map((school) => (
          <details className="school-card" key={school.id} style={{ "--school-color": school.color }}>
            <summary>{school.name} — level {school.level} <small>({school.experience}/{school.experience_to_next_level || "max"} xp)</small></summary>
            {school.description && <p>{school.description}</p>}
            <ul>
              {school.specialties.map((specialty) => (
                <li key={specialty.id}>{specialty.name}: level {specialty.level} (+{specialty.power_bonus_percent}% power) <small>{specialty.experience}/{specialty.experience_to_next_level || "max"} xp</small></li>
              ))}
            </ul>
          </details>
        ))}
      </section>
    </div>
  );
}
