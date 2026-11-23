// Ambient background: a slowly rotating wireframe sphere above a perspective grid floor.
(() => {
  const canvas = document.getElementById("bg");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w, h, dpr;

  const points = [];
  const N = 260;
  for (let i = 0; i < N; i++) {           // Fibonacci sphere
    const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), a = i * 2.399963;
    points.push([Math.cos(a) * r, y, Math.sin(a) * r]);
  }

  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    w = canvas.width = innerWidth * dpr;
    h = canvas.height = innerHeight * dpr;
  }
  addEventListener("resize", resize);
  resize();

  function frame(t) {
    ctx.clearRect(0, 0, w, h);
    const time = t / 1000;

    // grid floor
    const horizon = h * 0.62, vx = w / 2;
    ctx.lineWidth = dpr;
    for (let i = -14; i <= 14; i++) {
      ctx.strokeStyle = "rgba(90,120,255,0.10)";
      ctx.beginPath(); ctx.moveTo(vx + i * 14 * dpr, horizon); ctx.lineTo(vx + i * w * 0.16, h); ctx.stroke();
    }
    for (let j = 0; j < 14; j++) {
      const p = ((j + (time * 0.25) % 1) / 14) ** 2.2;
      ctx.strokeStyle = `rgba(90,120,255,${0.04 + p * 0.16})`;
      ctx.beginPath(); ctx.moveTo(0, horizon + p * (h - horizon)); ctx.lineTo(w, horizon + p * (h - horizon)); ctx.stroke();
    }

    // sphere
    const cx = w * 0.78, cy = h * 0.34, R = Math.min(w, h) * 0.26;
    const ay = time * 0.18, ax = 0.45 + Math.sin(time * 0.1) * 0.15;
    const sy = Math.sin(ay), cyy = Math.cos(ay), sx = Math.sin(ax), cxx = Math.cos(ax);
    const projected = points.map(([x, y, z]) => {
      const x1 = x * cyy - z * sy, z1 = x * sy + z * cyy;
      const y1 = y * cxx - z1 * sx, z2 = y * sx + z1 * cxx;
      const s = 2.4 / (2.4 + z2);
      return [cx + x1 * R * s, cy + y1 * R * s, z2];
    });
    for (let i = 0; i < N; i++) {
      const [x, y, z] = projected[i];
      const alpha = 0.12 + (1 - (z + 1) / 2) * 0.55;
      const next = projected[(i + 8) % N];
      ctx.strokeStyle = `rgba(34,211,238,${alpha * 0.22})`;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(next[0], next[1]); ctx.stroke();
      ctx.fillStyle = i % 5 ? `rgba(139,92,246,${alpha})` : `rgba(34,211,238,${alpha})`;
      ctx.beginPath(); ctx.arc(x, y, (1.1 + (1 - z) * 0.9) * dpr, 0, 6.283); ctx.fill();
    }
    if (!still) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
