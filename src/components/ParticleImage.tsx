import { useEffect, useRef } from 'react';

type Particle = {
  bx: number;
  by: number;
  bz: number;
  r: number;
  g: number;
  b: number;
  phaseX: number;
  phaseY: number;
  freqX: number;
  freqY: number;
  ampX: number;
  ampY: number;
  dx: number;
  dy: number;
  vx: number;
  vy: number;
};

export interface ParticleImageProps {
  /** A bold, high-contrast image. Transparent PNGs produce the cleanest silhouette. */
  src: string;
  /** Width and height of the square drawing surface in CSS pixels. */
  size?: number;
  /** Sampling interval in source pixels. Lower values produce denser marks. */
  gap?: number;
  dotRadius?: number;
  alphaThreshold?: number;
  /** Optional background color to key out, as `r,g,b`. Null disables color keying. */
  bgColor?: string | null;
  bgTolerance?: number;
  /** Brand color for all particles, as `r,g,b`. */
  color?: string;
  rotationSpeed?: number;
  swayAngle?: number;
  jiggle?: number;
  cursorRadius?: number;
  cursorStrength?: number;
  className?: string;
  ariaLabel?: string;
}

function parseRgb(value: string): [number, number, number] {
  const channels = value.split(',').map((channel) => Number.parseInt(channel.trim(), 10));
  return [channels[0] ?? 0, channels[1] ?? 0, channels[2] ?? 0];
}

/**
 * Samples an image into an interactive particle field. The resulting mark sways
 * in 3D, drifts continuously, and scatters away from the pointer before easing
 * back into place.
 */
export default function ParticleImage({
  src,
  size = 360,
  gap = 3,
  dotRadius = 1.35,
  alphaThreshold = 60,
  bgColor,
  bgTolerance = 42,
  color,
  rotationSpeed = 0.55,
  swayAngle = 0.5,
  jiggle = 2.2,
  cursorRadius = 80,
  cursorStrength = 3.2,
  className,
  ariaLabel = 'Animated particle logo',
}: ParticleImageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const particlesRef = useRef<Particle[]>([]);
  const mouseRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext('2d');
    if (!context) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    canvas.width = Math.floor(size * dpr);
    canvas.height = Math.floor(size * dpr);

    let animationFrame = 0;
    let disposed = false;
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.src = src;

    const buildParticles = () => {
      const sampleSize = 150;
      const ratio = Math.min(sampleSize / image.width, sampleSize / image.height, 1);
      const sampleWidth = Math.max(1, Math.round(image.width * ratio));
      const sampleHeight = Math.max(1, Math.round(image.height * ratio));
      const offscreen = document.createElement('canvas');
      offscreen.width = sampleWidth;
      offscreen.height = sampleHeight;

      const offscreenContext = offscreen.getContext('2d', { willReadFrequently: true });
      if (!offscreenContext) return;

      offscreenContext.clearRect(0, 0, sampleWidth, sampleHeight);
      offscreenContext.drawImage(image, 0, 0, sampleWidth, sampleHeight);

      let data: Uint8ClampedArray;
      try {
        data = offscreenContext.getImageData(0, 0, sampleWidth, sampleHeight).data;
      } catch {
        return;
      }

      const fit = (size * 0.8) / Math.max(sampleWidth, sampleHeight);
      const override = color ? parseRgb(color) : undefined;

      let background: [number, number, number] | null = null;
      if (bgColor !== null) {
        if (typeof bgColor === 'string') {
          background = parseRgb(bgColor);
        } else {
          const corners = [
            0,
            (sampleWidth - 1) * 4,
            (sampleHeight - 1) * sampleWidth * 4,
            ((sampleHeight - 1) * sampleWidth + sampleWidth - 1) * 4,
          ];
          const totals = corners.reduce<[number, number, number]>(
            (sum, index) => [
              sum[0] + (data[index] ?? 0),
              sum[1] + (data[index + 1] ?? 0),
              sum[2] + (data[index + 2] ?? 0),
            ],
            [0, 0, 0],
          );
          background = totals.map((total) => Math.round(total / 4)) as [number, number, number];
        }
      }

      const particles: Particle[] = [];
      for (let y = 0; y < sampleHeight; y += gap) {
        for (let x = 0; x < sampleWidth; x += gap) {
          const index = (y * sampleWidth + x) * 4;
          const red = data[index] ?? 0;
          const green = data[index + 1] ?? 0;
          const blue = data[index + 2] ?? 0;
          const alpha = data[index + 3] ?? 0;
          if (alpha <= alphaThreshold) continue;

          if (background) {
            const redDistance = red - background[0];
            const greenDistance = green - background[1];
            const blueDistance = blue - background[2];
            const distance = Math.hypot(redDistance, greenDistance, blueDistance);
            if (distance <= bgTolerance) continue;
          }

          particles.push({
            bx: (x - sampleWidth / 2) * fit,
            by: (y - sampleHeight / 2) * fit,
            bz: (Math.random() - 0.5) * size * 0.12,
            r: override?.[0] ?? red,
            g: override?.[1] ?? green,
            b: override?.[2] ?? blue,
            phaseX: Math.random() * Math.PI * 2,
            phaseY: Math.random() * Math.PI * 2,
            freqX: 0.8 + Math.random() * 1.4,
            freqY: 0.8 + Math.random() * 1.4,
            ampX: 0.6 + Math.random() * 1.1,
            ampY: 0.6 + Math.random() * 1.1,
            dx: 0,
            dy: 0,
            vx: 0,
            vy: 0,
          });
        }
      }
      particlesRef.current = particles;
    };

    const focalLength = size * 1.3;
    const center = size / 2;
    const render = (now: number) => {
      if (disposed) return;

      const time = reducedMotion ? 0 : now / 1000;
      const angleY = Math.sin(time * rotationSpeed) * swayAngle;
      const cosineY = Math.cos(angleY);
      const sineY = Math.sin(angleY);
      const tilt = Math.sin(time * 0.35) * 0.28;
      const cosineX = Math.cos(tilt);
      const sineX = Math.sin(tilt);

      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, size, size);

      for (const particle of particlesRef.current) {
        const rotatedX = particle.bx * cosineY + particle.bz * sineY;
        const rotatedZ = -particle.bx * sineY + particle.bz * cosineY;
        const rotatedY = particle.by * cosineX - rotatedZ * sineX;
        const depth = particle.by * sineX + rotatedZ * cosineX;
        const scale = focalLength / (focalLength - depth);
        const displacement = Math.hypot(particle.dx, particle.dy);
        const wander = reducedMotion ? 0 : jiggle * (1 + Math.min(displacement * 0.06, 2.2));
        const jitterX = Math.sin(time * particle.freqX + particle.phaseX) * particle.ampX * wander;
        const jitterY = Math.cos(time * particle.freqY + particle.phaseY) * particle.ampY * wander;
        const screenX = center + rotatedX * scale + jitterX + particle.dx;
        const screenY = center + rotatedY * scale + jitterY + particle.dy;

        if (!reducedMotion) {
          let accelerationX = -particle.dx * 0.08;
          let accelerationY = -particle.dy * 0.08;
          const mouse = mouseRef.current;

          if (mouse) {
            const distanceX = screenX - mouse.x;
            const distanceY = screenY - mouse.y;
            const distance = Math.hypot(distanceX, distanceY) || 0.0001;
            if (distance < cursorRadius) {
              const force = ((cursorRadius - distance) / cursorRadius) * cursorStrength;
              accelerationX += (distanceX / distance) * force;
              accelerationY += (distanceY / distance) * force;
            }
          }

          particle.vx = (particle.vx + accelerationX) * 0.82;
          particle.vy = (particle.vy + accelerationY) * 0.82;
          particle.dx += particle.vx;
          particle.dy += particle.vy;
        }

        const radius = dotRadius * scale;
        const alpha = Math.max(0.15, Math.min(1, scale * 0.9));
        context.beginPath();
        context.fillStyle = `rgba(${particle.r},${particle.g},${particle.b},${alpha})`;
        context.arc(screenX, screenY, radius, 0, Math.PI * 2);
        context.fill();
      }

      if (!reducedMotion) animationFrame = requestAnimationFrame(render);
    };

    const onLoad = () => {
      if (disposed) return;
      buildParticles();
      animationFrame = requestAnimationFrame(render);
    };

    if (image.complete && image.naturalWidth > 0) onLoad();
    else image.addEventListener('load', onLoad);

    const onPointerMove = (event: PointerEvent) => {
      const bounds = canvas.getBoundingClientRect();
      mouseRef.current = {
        x: ((event.clientX - bounds.left) / bounds.width) * size,
        y: ((event.clientY - bounds.top) / bounds.height) * size,
      };
    };
    const onPointerLeave = () => {
      mouseRef.current = null;
    };

    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerleave', onPointerLeave);

    return () => {
      disposed = true;
      cancelAnimationFrame(animationFrame);
      image.removeEventListener('load', onLoad);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerleave', onPointerLeave);
    };
  }, [
    alphaThreshold,
    bgColor,
    bgTolerance,
    color,
    cursorRadius,
    cursorStrength,
    dotRadius,
    gap,
    jiggle,
    rotationSpeed,
    size,
    src,
    swayAngle,
  ]);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={ariaLabel}
      className={className}
      style={{
        width: size,
        height: size,
        maxWidth: '100%',
        background: 'transparent',
        touchAction: 'none',
      }}
    />
  );
}
