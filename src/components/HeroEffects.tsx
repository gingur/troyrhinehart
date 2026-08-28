import { useEffect, useRef, useState } from 'react';

const COLUMN_COUNT = 24;
const GLOW_RADIUS = 2;

function gradientFor(
  hue: number,
  lightness: number,
  peakOpacity: number,
  peak: number,
  peakEnd: number,
  gain = 1,
) {
  const top = Math.min(1, peakOpacity * gain);
  const tail = Math.min(1, peakOpacity * 0.4 * gain);
  return `linear-gradient(180deg,
    transparent 0%,
    oklch(${lightness.toFixed(3)} 0.2 ${hue} / ${top.toFixed(3)}) ${peak.toFixed(1)}%,
    oklch(${(lightness - 0.05).toFixed(3)} 0.18 ${hue} / ${tail.toFixed(3)}) ${peakEnd.toFixed(1)}%,
    transparent ${Math.min(100, peakEnd + 20).toFixed(1)}%)`;
}

export default function HeroEffects() {
  const effectsRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [activeColumn, setActiveColumn] = useState<number | null>(null);

  useEffect(() => {
    const effects = effectsRef.current;
    if (!effects) return;

    const onMove = (event: PointerEvent) => {
      const rect = effects.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      ) {
        setActiveColumn(null);
        return;
      }
      const next = Math.min(
        COLUMN_COUNT - 1,
        Math.max(0, Math.floor(((event.clientX - rect.left) / rect.width) * COLUMN_COUNT)),
      );
      setActiveColumn((current) => (current === next ? current : next));
    };
    const reset = () => setActiveColumn(null);

    window.addEventListener('pointermove', onMove);
    window.addEventListener('blur', reset);
    document.documentElement.addEventListener('pointerleave', reset);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('blur', reset);
      document.documentElement.removeEventListener('pointerleave', reset);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const effects = effectsRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !effects || !context) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const pointer = { x: -10_000, y: -10_000 };
    let width = 0;
    let height = 0;
    let frame = 0;
    let particles: Array<{ x: number; y: number; vx: number; vy: number; radius: number }> = [];

    const build = () => {
      const rect = effects.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const count = Math.min(54, Math.max(16, Math.floor((width * height) / 26_000)));
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.28,
        vy: (Math.random() - 0.5) * 0.28,
        radius: Math.random() * 1.3 + 0.55,
      }));
    };

    const draw = () => {
      context.clearRect(0, 0, width, height);

      for (const particle of particles) {
        if (!reduceMotion) {
          particle.x += particle.vx;
          particle.y += particle.vy;
          const deltaX = particle.x - pointer.x;
          const deltaY = particle.y - pointer.y;
          const distance = Math.hypot(deltaX, deltaY);
          if (distance < 125 && distance > 0) {
            const force = (125 - distance) / 125;
            particle.x += (deltaX / distance) * force * 1.25;
            particle.y += (deltaY / distance) * force * 1.25;
          }

          if (particle.x < 0) particle.x = width;
          if (particle.x > width) particle.x = 0;
          if (particle.y < 0) particle.y = height;
          if (particle.y > height) particle.y = 0;
        }

        context.beginPath();
        context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        context.fillStyle = 'rgba(200, 255, 61, 0.82)';
        context.fill();
      }

      for (let first = 0; first < particles.length; first += 1) {
        for (let second = first + 1; second < particles.length; second += 1) {
          const a = particles[first]!;
          const b = particles[second]!;
          const distance = Math.hypot(a.x - b.x, a.y - b.y);
          if (distance >= 135) continue;
          context.beginPath();
          context.moveTo(a.x, a.y);
          context.lineTo(b.x, b.y);
          context.strokeStyle = `rgba(200, 255, 61, ${0.2 * (1 - distance / 135)})`;
          context.lineWidth = 0.8;
          context.stroke();
        }
      }

      if (!reduceMotion) frame = requestAnimationFrame(draw);
    };

    const onMove = (event: PointerEvent) => {
      const rect = effects.getBoundingClientRect();
      pointer.x = event.clientX - rect.left;
      pointer.y = event.clientY - rect.top;
    };
    const resetPointer = () => {
      pointer.x = -10_000;
      pointer.y = -10_000;
    };
    const observer = new ResizeObserver(() => {
      build();
      if (reduceMotion) draw();
    });

    build();
    draw();
    observer.observe(effects);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerleave', resetPointer);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerleave', resetPointer);
    };
  }, []);

  const center = (COLUMN_COUNT - 1) / 2;

  return (
    <div className="hero-effects" ref={effectsRef} aria-hidden="true">
      <div className="hero-chandelier">
        {Array.from({ length: COLUMN_COUNT }, (_, index) => {
          const falloff = 1 - Math.abs(index - center) / (center + 1);
          const centerBias = 0.45 + 0.55 * Math.pow(falloff, 1.2);
          const random = (seed: number) => {
            const value = Math.sin((index + 1) * seed) * 43_758.5453;
            return value - Math.floor(value);
          };
          const first = random(12.9898);
          const second = random(78.233);
          const intensity = centerBias * (0.3 + 0.9 * first);
          const peak = 8 + 26 * second;
          const peakStart = Math.max(0, peak - (5 + 6 * first));
          const peakEnd = peak + (16 + 30 * intensity);
          const peakOpacity = 0.1 + 0.42 * intensity;
          const lightness = 0.76 + 0.16 * intensity;
          const distance = activeColumn === null ? Infinity : Math.abs(index - activeColumn);
          const proximity = distance > GLOW_RADIUS ? 0 : 1 - distance / (GLOW_RADIUS + 1);
          const mask = `linear-gradient(180deg, transparent 0%, black ${peakStart.toFixed(1)}%, black 100%)`;

          return (
            <i
              className="chandelier-column"
              style={{
                filter: `brightness(${1 + 0.42 * proximity})`,
                transform: `translateY(${-7 * proximity}px)`,
              }}
              key={index}
            >
              <b
                style={{
                  background: gradientFor(122, lightness, peakOpacity, peak, peakEnd),
                  maskImage: mask,
                  WebkitMaskImage: mask,
                }}
              />
              <b
                className="chandelier-hot"
                style={{
                  background: gradientFor(42, lightness, peakOpacity, peak, peakEnd, 2.7),
                  maskImage: mask,
                  opacity: proximity,
                  WebkitMaskImage: mask,
                }}
              />
            </i>
          );
        })}
      </div>
      <canvas className="hero-particles" ref={canvasRef} />
      <div className="hero-vignette" />
    </div>
  );
}
