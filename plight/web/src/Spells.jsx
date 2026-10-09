import { useEffect, useRef, useState } from "react";

export const SPELL_ANIMATIONS = ["bolt", "beam", "burst", "nova", "ring", "aura", "rain", "spiral"];

export function SpellEffectsOverlay({ casts, onDone }) {
  useEffect(() => {
    if (!casts?.length) return undefined;
    const timer = setTimeout(onDone, 2600);
    return () => clearTimeout(timer);
  }, [casts, onDone]);
  if (!casts?.length) return null;
  return (
    <div className="spell-overlay" aria-hidden="true">
      {casts.map((cast, index) => <SpellVisual key={`${cast.spell_id}-${index}`} visual={cast.visual} delay={index * 450} width={640} height={420} />)}
    </div>
  );
}

const TAU = Math.PI * 2;
const rand = (min, max) => min + Math.random() * (max - min);

function makeParticles(animation, count, w, h) {
  const cx = w / 2;
  const cy = h / 2;
  const list = [];
  for (let i = 0; i < count; i += 1) {
    const p = { x: cx, y: cy, vx: 0, vy: 0, delay: 0, life: 1, size: rand(2, 5), polar: null, alt: Math.random() < 0.5 };
    const angle = rand(0, TAU);
    if (animation === "bolt") {
      if (i < count * 0.6) {
        p.x = w * 0.08; p.y = h * 0.8; p.delay = rand(0, 0.5); p.life = 0.55;
        p.vx = (cx - p.x) / p.life + rand(-30, 30); p.vy = (cy - p.y) / p.life + rand(-30, 30);
      } else {
        p.delay = 0.55 + rand(0, 0.1); p.life = 0.9;
        const speed = rand(40, 200);
        p.vx = Math.cos(angle) * speed; p.vy = Math.sin(angle) * speed;
      }
    } else if (animation === "beam") {
      p.x = w * 0.05; p.y = cy + rand(-8, 8); p.delay = rand(0, 0.7); p.life = 0.5;
      p.vx = (cx - p.x) / p.life; p.vy = rand(-12, 12);
      if (i > count * 0.75) { p.x = cx; p.vx = rand(-40, 40); p.vy = rand(-100, 100); p.delay = 0.5 + rand(0, 0.3); }
    } else if (animation === "burst") {
      const speed = rand(60, 260);
      p.vx = Math.cos(angle) * speed; p.vy = Math.sin(angle) * speed; p.life = rand(0.7, 1.2);
    } else if (animation === "nova") {
      const speed = rand(250, 290);
      p.vx = Math.cos(angle) * speed; p.vy = Math.sin(angle) * speed; p.life = 1;
    } else if (animation === "ring") {
      p.polar = { angle, radius: 100, spin: 3.2, shrink: 0 }; p.life = 1.5; p.delay = rand(0, 0.3);
    } else if (animation === "aura") {
      const radius = rand(10, 70);
      p.x = cx + Math.cos(angle) * radius; p.y = cy + 50 + Math.sin(angle) * radius * 0.4;
      p.vy = rand(-90, -40); p.vx = rand(-12, 12); p.delay = rand(0, 1); p.life = rand(0.9, 1.4);
    } else if (animation === "rain") {
      p.x = cx + rand(-130, 130); p.y = -10; p.vy = rand(260, 380); p.delay = rand(0, 1); p.life = (cy + 20) / p.vy + rand(0, 0.2);
    } else if (animation === "spiral") {
      p.polar = { angle: angle, radius: 150, spin: 7, shrink: 130 }; p.life = 1.2; p.delay = rand(0, 0.5);
    }
    list.push(p);
  }
  return list;
}

function drawParticle(ctx, p, shape, color, alpha, age, rotation) {
  ctx.globalAlpha = Math.max(0, alpha);
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  if (shape === "sparks") {
    const length = 7 + p.size * 2;
    const speed = Math.hypot(p.vx, p.vy) || 1;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x - (p.vx / speed) * length, p.y - (p.vy / speed) * length);
    ctx.stroke();
  } else if (shape === "stars") {
    const r = p.size * 1.8;
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(rotation);
    ctx.beginPath();
    for (let k = 0; k < 8; k += 1) {
      const radius = k % 2 === 0 ? r : r * 0.35;
      const a = (k / 8) * TAU;
      ctx.lineTo(Math.cos(a) * radius, Math.sin(a) * radius);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  } else if (shape === "bubbles") {
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size * 1.6, 0, TAU);
    ctx.stroke();
  } else if (shape === "smoke") {
    const radius = p.size * (3 + age * 6);
    const gradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
    gradient.addColorStop(0, color);
    gradient.addColorStop(1, "transparent");
    ctx.globalAlpha = Math.max(0, alpha) * 0.35;
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, TAU);
    ctx.fill();
  } else {
    ctx.beginPath();
    ctx.arc(p.x, p.y, shape === "snow" ? p.size * 0.9 : p.size, 0, TAU);
    ctx.fill();
  }
}

export function SpellVisual({ visual, delay = 0, loop = false, width = 320, height = 180 }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext("2d");
    const { animation = "bolt", color = "#ff8a3d", secondary_color: secondary, intensity = 2, particle_effect: effect = "sparks" } = visual || {};
    const colors = [color, secondary || color];
    const shape = effect === "none" ? "dots" : effect;
    const count = 45 + intensity * 35;
    const scale = Math.min(width / 640, height / 420) < 0.6 ? 0.55 : 1;
    let particles = makeParticles(animation, count, width / scale, height / scale);
    let start = performance.now() + delay;
    let last = start;
    let frame = 0;
    function tick(now) {
      frame = requestAnimationFrame(tick);
      if (now < start) return;
      const dt = Math.min(0.05, (now - last) / 1000);
      const elapsed = (now - start) / 1000;
      last = now;
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.clearRect(0, 0, width / scale, height / scale);
      ctx.globalCompositeOperation = shape === "smoke" ? "source-over" : "lighter";
      let alive = 0;
      const cx = width / scale / 2;
      const cy = height / scale / 2;
      for (const p of particles) {
        const age = (elapsed - p.delay) / p.life;
        if (age < 0) { alive += 1; continue; }
        if (age >= 1) continue;
        alive += 1;
        if (p.polar) {
          p.polar.angle += p.polar.spin * dt;
          p.polar.radius = Math.max(0, p.polar.radius - p.polar.shrink * dt);
          p.x = cx + Math.cos(p.polar.angle) * p.polar.radius;
          p.y = cy + Math.sin(p.polar.angle) * p.polar.radius * 0.7;
          p.vx = -Math.sin(p.polar.angle) * 40; p.vy = Math.cos(p.polar.angle) * 40;
        } else {
          p.x += p.vx * dt;
          p.y += p.vy * dt;
          if (shape === "embers") { p.vy -= 70 * dt; p.x += Math.sin(elapsed * 6 + p.size) * 0.6; }
          else if (shape === "snow") { p.vy += 40 * dt; p.vx *= 0.98; p.x += Math.sin(elapsed * 3 + p.size * 3) * 0.8; }
          else if (shape === "bubbles") { p.vy -= 35 * dt; p.vx *= 0.97; }
          else if (shape === "smoke") { p.vy -= 20 * dt; p.vx *= 0.97; }
        }
        const fade = age < 0.15 ? age / 0.15 : 1 - (age - 0.15) / 0.85;
        drawParticle(ctx, p, shape, colors[p.alt ? 1 : 0], fade, age, elapsed * 3 + p.size);
      }
      ctx.globalAlpha = 1;
      if (alive === 0) {
        if (loop) {
          particles = makeParticles(animation, count, width / scale, height / scale);
          start = now + 250;
        } else {
          ctx.clearRect(0, 0, width / scale, height / scale);
          cancelAnimationFrame(frame);
        }
      }
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [visual, delay, loop, width, height]);
  return <canvas className="spell-canvas" height={height} ref={canvasRef} width={width} />;
}
export function SpellsDialog({ busy, enemies, magic, onCast, onClose, onEditSlot }) {
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
        <h3>Edit spellbooks</h3>
        {(magic?.books || []).length === 0 && <p className="inventory-empty">You are not carrying a spellbook.</p>}
        {(magic?.books || []).map((entry) => (
          <article className="spellbook-editor" key={entry.id}>
            <strong>{entry.name}{entry.equipped ? " (equipped)" : ""}</strong>
            {entry.slots.map((slot) => {
              const others = new Set(entry.slots.filter((other) => other.index !== slot.index && other.spell).map((other) => other.spell.id));
              const options = (magic.known_spells || []).filter((spell) => (
                (!slot.school_id || spell.school_id === slot.school_id)
                && (!slot.max_level || spell.required_level <= slot.max_level)
                && !others.has(spell.id)
              ));
              return (
                <label className="spellbook-slot" key={slot.index}>
                  <span>{slot.label}{slot.school_id ? ` · ${slot.school_id}` : ""}{slot.max_level ? ` · max level ${slot.max_level}` : ""}</span>
                  <select disabled={busy} onChange={(event) => onEditSlot(entry.id, slot.index, event.target.value || null)} value={slot.spell?.id || ""}>
                    <option value="">Empty</option>
                    {slot.spell && !options.some((spell) => spell.id === slot.spell.id) && <option value={slot.spell.id}>{slot.spell.name}</option>}
                    {options.map((spell) => <option key={spell.id} value={spell.id}>{spell.name} (level {spell.required_level}, {spell.specialty_name})</option>)}
                  </select>
                </label>
              );
            })}
          </article>
        ))}
        <h3>Known spells ({(magic?.known_spells || []).length})</h3>
        <div className="spell-slots">
          {(magic?.known_spells || []).map((spell) => (
            <article className="spell-card" key={spell.id} style={{ "--school-color": spell.school_color }}>
              <strong>{spell.name}</strong>
              <span>{spell.school_name} / {spell.specialty_name} · level {spell.required_level} · {spell.mana_cost} mana</span>
              <ul>{spell.effects.map((effect) => <li key={effect}>{effect}</li>)}</ul>
              {spell.blocker && !spell.blocker.includes("mana") && <em>{spell.blocker}</em>}
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
