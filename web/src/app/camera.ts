export type Quality = {
  ready: boolean;
  reason: 'hold_still' | 'improve_lighting' | 'focus' | 'ready';
  sharpness: number;
  brightness: number;
  motion: number;
  fingerprint: Uint8Array;
};

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
    this.last = gray;
    const brightness = sum / gray.length;
    const motionScore = motion / gray.length;
    const sharpnessScore = sharpness / ((width - 2) * (height - 2));
    const fingerprint = new Uint8Array(64);
    for (let y = 0; y < 8; y++)
      for (let x = 0; x < 8; x++) fingerprint[y * 8 + x] = gray[(y * 15 + 7) * width + x * 20 + 10];
    const reason =
      brightness < 55 || brightness > 220 || clipped / gray.length > 0.7
        ? 'improve_lighting'
        : motionScore > 9
          ? 'hold_still'
          : sharpnessScore < 13
            ? 'focus'
            : 'ready';
    return {
      ready: reason === 'ready' && hadLast,
      reason,
      sharpness: sharpnessScore,
      brightness,
      motion: motionScore,
      fingerprint,
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
