export type Quality = {
  ready: boolean;
  reason: 'hold_still' | 'improve_lighting' | 'focus' | 'ready';
  sharpness: number;
  brightness: number;
  motion: number;
  rawMotion: number;
  fingerprint: Uint8Array;
  framing: Uint8Array;
};

function motionAfterSmallShift(
  current: Uint8Array,
  previous: Uint8Array,
  width: number,
  height: number,
): number {
  let best = Infinity;
  // Allow hand tremor without treating high-contrast print edges as a large movement.
  for (let dy = -3; dy <= 3; dy++) {
    for (let dx = -3; dx <= 3; dx++) {
      let difference = 0;
      let count = 0;
      for (let y = 3; y < height - 3; y += 2) {
        for (let x = 3; x < width - 3; x += 2) {
          const index = y * width + x;
          difference += Math.abs(current[index] - previous[index + dy * width + dx]);
          count++;
        }
      }
      best = Math.min(best, difference / count);
    }
  }
  return best;
}

type PhotoTrack = MediaStreamTrack & {
  getCapabilities?: () => MediaTrackCapabilities & { torch?: boolean };
};
type PhotoCapture = { takePhoto: () => Promise<Blob> };
type PhotoCaptureConstructor = new (track: MediaStreamTrack) => PhotoCapture;

export class CameraCapture {
  private canvas = document.createElement('canvas');
  private context = this.canvas.getContext('2d', { willReadFrequently: true })!;
  private last?: Uint8Array;
  stream?: MediaStream;
  track?: PhotoTrack;

  constructor(readonly video: HTMLVideoElement) {
    this.canvas.width = 160;
    this.canvas.height = 120;
  }

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
    });
    this.track = this.stream.getVideoTracks()[0];
    this.video.srcObject = this.stream;
    await this.video.play();
  }

  stop(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = undefined;
    this.track = undefined;
    this.video.srcObject = null;
    this.last = undefined;
  }

  dimensions(): { width: number; height: number } {
    return { width: this.video.videoWidth, height: this.video.videoHeight };
  }

  resetMotion(): void {
    this.last = undefined;
  }

  sample(): Quality | undefined {
    if (!this.video.videoWidth) return undefined;
    const width = this.canvas.width;
    const height = this.canvas.height;
    this.context.drawImage(this.video, 0, 0, width, height);
    const rgba = this.context.getImageData(0, 0, width, height).data;
    const hadLast = !!this.last;
    const gray = new Uint8Array(width * height);
    let sum = 0;
    let clipped = 0;
    let motion = 0;
    for (let i = 0; i < gray.length; i++) {
      const pixel = i * 4;
      const value = Math.round(
        0.2126 * rgba[pixel] + 0.7152 * rgba[pixel + 1] + 0.0722 * rgba[pixel + 2],
      );
      gray[i] = value;
      sum += value;
      if (value < 14 || value > 245) clipped++;
      if (this.last) motion += Math.abs(value - this.last[i]);
    }
    let sharpness = 0;
    for (let y = 1; y < height - 1; y++) {
      for (let x = 1; x < width - 1; x++) {
        const i = y * width + x;
        sharpness += Math.abs(
          4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - width] - gray[i + width],
        );
      }
    }
    const brightness = sum / gray.length;
    const rawMotion = motion / gray.length;
    const motionScore = this.last ? motionAfterSmallShift(gray, this.last, width, height) : 0;
    this.last = gray;
    const sharpnessScore = sharpness / ((width - 2) * (height - 2));
    const fingerprint = new Uint8Array(64);
    for (let y = 0; y < 8; y++)
      for (let x = 0; x < 8; x++) fingerprint[y * 8 + x] = gray[(y * 15 + 7) * width + x * 20 + 10];
    const reason =
      brightness < 55 || brightness > 220 || clipped / gray.length > 0.7
        ? 'improve_lighting'
        : sharpnessScore < 13
          ? 'focus'
          : motionScore > 18
            ? 'hold_still'
            : 'ready';
    return {
      ready: reason === 'ready' && hadLast,
      reason,
      sharpness: sharpnessScore,
      brightness,
      motion: motionScore,
      rawMotion,
      fingerprint,
      framing: framingSample(gray),
    };
  }

  async takeStill(): Promise<{
    blob: Blob;
    method: string;
    width: number;
    height: number;
    fallback?: string;
  }> {
    if (!this.track) throw new Error('Camera stopped');
    const constructor = (window as Window & { ImageCapture?: PhotoCaptureConstructor })
      .ImageCapture;
    let fallback = 'photo_api_unavailable';
    if (constructor) {
      let timeout: number | undefined;
      try {
        let blob = await Promise.race([
          new constructor(this.track).takePhoto(),
          new Promise<never>((_, reject) => {
            timeout = window.setTimeout(() => reject(new Error('photo_timeout')), 5000);
          }),
        ]);
        const bitmap = await createImageBitmap(blob);
        const dimensions = { width: bitmap.width, height: bitmap.height };
        if (
          !['image/jpeg', 'image/png', 'image/webp'].includes(blob.type) ||
          blob.size > 11_000_000
        ) {
          const canvas = document.createElement('canvas');
          canvas.width = bitmap.width;
          canvas.height = bitmap.height;
          canvas.getContext('2d')!.drawImage(bitmap, 0, 0);
          blob = await new Promise<Blob>((resolve, reject) =>
            canvas.toBlob(
              (value) => (value ? resolve(value) : reject(new Error('Photo conversion failed'))),
              'image/jpeg',
              0.9,
            ),
          );
        }
        bitmap.close();
        return { blob, method: 'image_capture', ...dimensions };
      } catch (error) {
        fallback =
          error instanceof Error && error.message === 'photo_timeout'
            ? 'photo_timeout'
            : 'photo_failed';
      } finally {
        window.clearTimeout(timeout);
      }
    }
    if (!this.track || !this.video.videoWidth) throw new Error('Camera stopped');
    const canvas = document.createElement('canvas');
    canvas.width = this.video.videoWidth;
    canvas.height = this.video.videoHeight;
    canvas.getContext('2d')!.drawImage(this.video, 0, 0);
    const blob = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (value) => (value ? resolve(value) : reject(new Error('Frame capture failed'))),
        'image/jpeg',
        0.94,
      ),
    );
    return { blob, method: 'video_frame', width: canvas.width, height: canvas.height, fallback };
  }

  async torch(enabled: boolean): Promise<boolean> {
    const capabilities = this.track?.getCapabilities?.() as
      (MediaTrackCapabilities & { torch?: boolean }) | undefined;
    if (!capabilities?.torch) return false;
    await this.track!.applyConstraints({
      advanced: [{ torch: enabled } as MediaTrackConstraintSet],
    });
    return true;
  }
}

export function fingerprintDistance(a: Uint8Array, b: Uint8Array): number {
  return a.reduce((sum, value, i) => sum + Math.abs(value - b[i]), 0) / a.length;
}

// Average before registration so individual print edges and sensor noise do not dominate.
function framingSample(gray: Uint8Array): Uint8Array {
  const frame = new Uint8Array(80 * 60);
  for (let y = 0; y < 60; y++) {
    for (let x = 0; x < 80; x++) {
      const i = y * 320 + x * 2;
      frame[y * 80 + x] = (gray[i] + gray[i + 1] + gray[i + 160] + gray[i + 161]) / 4;
    }
  }
  return frame;
}

export type Enlargement = {
  ready: boolean;
  scale: number;
  correlation: number;
  separation: number;
};

export function measureEnlargement(reference: Uint8Array, current: Uint8Array): Enlargement {
  const smooth = (frame: Uint8Array): Uint8Array => {
    const result = frame.slice();
    for (let y = 1; y < 59; y++) {
      for (let x = 1; x < 79; x++) {
        const i = y * 80 + x;
        result[i] =
          (frame[i] * 4 +
            (frame[i - 1] + frame[i + 1] + frame[i - 80] + frame[i + 80]) * 2 +
            frame[i - 81] +
            frame[i - 79] +
            frame[i + 79] +
            frame[i + 81]) /
          16;
      }
    }
    return result;
  };
  // Suppress fine-line aliasing before comparing differently sized views.
  reference = smooth(smooth(reference));
  current = smooth(smooth(current));
  let best = { scale: 1, correlation: -1 };
  let unchanged = -1;
  const correlationAt = (scale: number, dx: number, dy: number): number => {
    let a = 0,
      b = 0,
      aa = 0,
      bb = 0,
      ab = 0,
      count = 0;
    for (let y = 14; y < 46; y += 2) {
      const ry = 30 + (y - 30 - dy) / scale;
      if (ry < 0 || ry >= 59) continue;
      const iy = Math.floor(ry),
        fy = ry - iy;
      for (let x = 20; x < 60; x += 2) {
        const rx = 40 + (x - 40 - dx) / scale;
        if (rx < 0 || rx >= 79) continue;
        const ix = Math.floor(rx),
          fx = rx - ix;
        const i = iy * 80 + ix;
        const v =
          (reference[i] * (1 - fx) + reference[i + 1] * fx) * (1 - fy) +
          (reference[i + 80] * (1 - fx) + reference[i + 81] * fx) * fy;
        const w = current[y * 80 + x];
        a += v;
        b += w;
        aa += v * v;
        bb += w * w;
        ab += v * w;
        count++;
      }
    }
    const va = aa - (a * a) / count,
      vb = bb - (b * b) / count;
    if (count < 300 || va / count < 36 || vb / count < 36) return -1;
    return (ab - (a * b) / count) / Math.sqrt(va * vb);
  };
  // Translation absorbs hand tremor and small reframing; normalized correlation rejects lighting changes.
  for (const scale of [0.9, 1, 1.06, 1.12, 1.18, 1.26, 1.36, 1.5, 1.6, 1.7, 2]) {
    let score = -1,
      bestX = 0,
      bestY = 0;
    for (let dy = -12; dy <= 12; dy += 2) {
      for (let dx = -12; dx <= 12; dx += 2) {
        const candidate = correlationAt(scale, dx, dy);
        if (candidate > score) {
          score = candidate;
          bestX = dx;
          bestY = dy;
        }
      }
    }
    for (let dy = bestY - 1; dy <= bestY + 1; dy++)
      for (let dx = bestX - 1; dx <= bestX + 1; dx++)
        score = Math.max(score, correlationAt(scale, dx, dy));
    if (scale <= 1.12) unchanged = Math.max(unchanged, score);
    if (score > best.correlation) best = { scale, correlation: score };
  }
  const separation = best.correlation - unchanged;
  return {
    ...best,
    separation,
    ready: best.scale >= 1.18 && best.correlation >= 0.8 && separation >= 0.05,
  };
}
