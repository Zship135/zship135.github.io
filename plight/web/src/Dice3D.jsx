import { useEffect, useMemo, useRef } from "react";

const PHI = (1 + Math.sqrt(5)) / 2;
const SCALE = 30;
const TUMBLE_AXIS = [0.62, 0.78, 0.35];
const TUMBLE_SPEED = 9;
const SETTLE_MS = 1400;
const EXTRA_SPINS = 2;

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a) => Math.hypot(a[0], a[1], a[2]);
const norm = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

function buildFaces() {
  const verts = [];
  for (const a of [-1, 1]) for (const b of [-PHI, PHI]) {
    verts.push([0, a, b], [a, b, 0], [b, 0, a]);
  }
  const near = (i, j) => Math.abs(len(sub(verts[i], verts[j])) - 2) < 1e-6;
  const faces = [];
  for (let i = 0; i < 12; i++) for (let j = i + 1; j < 12; j++) for (let k = j + 1; k < 12; k++) {
    if (!near(i, j) || !near(j, k) || !near(i, k)) continue;
    const [a, b, c] = [verts[i], verts[j], verts[k]];
    const centroid = [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3];
    const z = norm(centroid);
    const yDir = norm(sub([(b[0] + c[0]) / 2, (b[1] + c[1]) / 2, (b[2] + c[2]) / 2], a));
    const x = norm(cross(yDir, z));
    const y = cross(z, x);
    faces.push({ x, y, z, inradius: len(centroid) * SCALE });
  }
  // Opposite faces sum to 21, like a real d20.
  let next = 1;
  faces.forEach((face, i) => {
    if (face.number) return;
    const opposite = faces.findIndex((other, j) => j !== i && dot(other.z, face.z) < -0.999);
    face.number = next;
    faces[opposite].number = 21 - next;
    next += 1;
  });
  return faces;
}

const qMul = (a, b) => [
  a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
  a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
  a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
  a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
];
const qAxis = (axis, angle) => {
  const s = Math.sin(angle / 2);
  return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(angle / 2)];
};
const qNorm = (q) => { const l = Math.hypot(...q) || 1; return q.map((v) => v / l); };
function qSlerp(a, b, t) {
  let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
  let target = b;
  if (d < 0) { d = -d; target = b.map((v) => -v); }
  if (d > 0.9995) return qNorm(a.map((v, i) => v + (target[i] - v) * t));
  const theta = Math.acos(d);
  const sa = Math.sin((1 - t) * theta) / Math.sin(theta);
  const sb = Math.sin(t * theta) / Math.sin(theta);
  return a.map((v, i) => v * sa + target[i] * sb);
}
function qMatrix([x, y, z, w]) {
  return [
    1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
    2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
    2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
    0, 0, 0, 1,
  ];
}
// Quaternion rotating a face's frame onto the screen frame (normal toward viewer, apex up).
function faceQuaternion({ x, y, z }) {
  const m = [x[0], x[1], x[2], y[0], y[1], y[2], z[0], z[1], z[2]];
  const trace = m[0] + m[4] + m[8];
  let q;
  if (trace > 0) {
    const s = Math.sqrt(trace + 1) * 2;
    q = [(m[7] - m[5]) / s, (m[2] - m[6]) / s, (m[3] - m[1]) / s, s / 4];
  } else if (m[0] > m[4] && m[0] > m[8]) {
    const s = Math.sqrt(1 + m[0] - m[4] - m[8]) * 2;
    q = [s / 4, (m[1] + m[3]) / s, (m[2] + m[6]) / s, (m[7] - m[5]) / s];
  } else if (m[4] > m[8]) {
    const s = Math.sqrt(1 + m[4] - m[0] - m[8]) * 2;
    q = [(m[1] + m[3]) / s, s / 4, (m[5] + m[7]) / s, (m[2] - m[6]) / s];
  } else {
    const s = Math.sqrt(1 + m[8] - m[0] - m[4]) * 2;
    q = [(m[2] + m[6]) / s, (m[5] + m[7]) / s, s / 4, (m[3] - m[1]) / s];
  }
  return qNorm(q);
}

const FACES = buildFaces();
const EDGE = 2 * SCALE;
const HEIGHT = (EDGE * Math.sqrt(3)) / 2;
const easeOut = (t) => 1 - (1 - t) ** 3;

function faceTransform({ x, y, z, inradius }) {
  const m = [...x, 0, ...y, 0, ...z, 0, z[0] * inradius, z[1] * inradius, z[2] * inradius, 1];
  return `matrix3d(${m.join(",")})`;
}

export default function Dice3D({ value, label }) {
  const cubeRef = useRef(null);
  const shadowRef = useRef(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const faces = useMemo(() => FACES, []);

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const axis = norm(TUMBLE_AXIS);
    let q = qNorm([Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5, Math.random() + 0.2]);
    let last = performance.now();
    let start = last;
    let settle = null;
    let frame = 0;

    const paint = (rotation, lift, scale) => {
      if (cubeRef.current) {
        cubeRef.current.style.transform = `translateY(${-lift}px) scale(${scale}) matrix3d(${qMatrix(rotation).join(",")})`;
      }
      if (shadowRef.current) {
        const s = Math.max(0.35, 1 - lift / 110) * scale;
        shadowRef.current.style.transform = `translate(-50%, 0) scale(${s})`;
        shadowRef.current.style.opacity = String(0.55 * Math.max(0.3, 1 - lift / 120));
      }
    };

    const tick = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const elapsed = (now - start) / 1000;
      const entrance = easeOut(Math.min(1, elapsed / 0.35));
      const scale = 0.45 + 0.55 * entrance;

      if (valueRef.current != null && !settle && (reduced || elapsed > 0.9)) {
        const face = FACES.find((f) => f.number === valueRef.current) || FACES[0];
        settle = { from: q, to: faceQuaternion(face), begin: now };
        if (reduced) settle.begin = now - SETTLE_MS;
      }

      if (!settle) {
        q = qNorm(qMul(qAxis(axis, TUMBLE_SPEED * dt), q));
        paint(q, Math.abs(Math.sin(elapsed * 6)) * 26 * entrance, scale);
      } else {
        const t = Math.min(1, (now - settle.begin) / SETTLE_MS);
        const e = easeOut(t);
        const spin = qAxis(axis, (1 - e) * EXTRA_SPINS * Math.PI * 2);
        q = qNorm(qMul(spin, qSlerp(settle.from, settle.to, e)));
        const lift = Math.abs(Math.sin(t * Math.PI * 3)) * 26 * (1 - t) ** 1.5;
        paint(q, lift, scale);
        if (t >= 1) return;
      }
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className="d20">
      <div className="d20-scene">
        <div className="d20-shadow" ref={shadowRef} />
        <div className="d20-body" ref={cubeRef}>
          {faces.map((face) => (
            <div
              className="d20-face"
              key={face.number}
              style={{
                width: EDGE + 1,
                height: HEIGHT + 1,
                left: -(EDGE + 1) / 2,
                top: -(HEIGHT * 2) / 3,
                transform: faceTransform(face),
                "--shade": (0.72 + 0.28 * ((face.number * 7) % 5) / 4).toFixed(2),
              }}
            >
              <div className="d20-face-inner">
                <span className={face.number === 6 || face.number === 9 ? "underlined" : undefined}>{face.number}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
      <small className={`d20-label${value != null ? " revealed" : ""}`}>{value != null ? `${label} · ${value}` : "\u00a0"}</small>
    </div>
  );
}
