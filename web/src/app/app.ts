import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnDestroy, OnInit, ViewChild, signal } from '@angular/core';
import { Api, Guidance, GuidanceAction, Results, Session } from './api';
import { CameraCapture, fingerprintDistance, Quality } from './camera';
import { Diagnostics } from './diagnostics';
import {
  activeObservation,
  clearStills,
  pendingStills,
  removeStill,
  savedSession,
  saveActiveObservation,
  saveSession,
  saveStill,
} from './storage';

const cues: Record<GuidanceAction, { icon: string; label: string }> = {
  move_left: { icon: '←', label: 'Move left' },
  move_right: { icon: '→', label: 'Move right' },
  move_up: { icon: '↑', label: 'Move up' },
  move_down: { icon: '↓', label: 'Move down' },
  closer: { icon: '⊕', label: 'Move closer' },
  farther: { icon: '⊖', label: 'Move farther' },
  tilt_left: { icon: '↶', label: 'Tilt left' },
  tilt_right: { icon: '↷', label: 'Tilt right' },
  hold_still: { icon: '◎', label: 'Hold still' },
  improve_lighting: { icon: '☀', label: 'Improve lighting' },
  show_full_pattern: { icon: '▣', label: 'Show the full pattern' },
  scan_next: { icon: '▦', label: 'Find another pattern' },
  complete: { icon: '✓', label: 'Scan complete' },
  inconclusive: { icon: '?', label: 'More detail needed' },
  stop: { icon: '■', label: 'Scan stopped' },
};

@Component({
  selector: 'app-root',
  imports: [CommonModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit, OnDestroy {
  @ViewChild('preview') preview?: ElementRef<HTMLVideoElement>;
  readonly phase = signal<'welcome' | 'starting' | 'scanning' | 'processing' | 'results' | 'error'>(
    'welcome',
  );
  readonly cue = signal(cues.show_full_pattern);
  readonly visualAction = signal<GuidanceAction>('show_full_pattern');
  readonly guidance = signal<Guidance>({ action: 'show_full_pattern' });
  readonly results = signal<Results>({ revision: 0, rows: [], unresolved: [], conflicts: [] });
  readonly error = signal('');
  readonly metrics = signal('');
  readonly progress = signal('Ready');
  readonly hasSavedSession = signal(false);
  readonly copied = signal(false);
  readonly expandedEvidence = signal(false);
  private api = new Api();
  private log = new Diagnostics();
  private camera?: CameraCapture;
  private session?: Session;
  private timer?: number;
  private tickBusy = false;
  private stableFrames = 0;
  private captureCount = 0;
  private lastCaptureAt = 0;
  private lastFingerprint?: Uint8Array;
  private lastQualityLog = 0;
  private scanNextSince?: number;
  private activeObservation?: string;
  private torchAttempted = false;
  private torchAt?: number;
  private torchBaseline?: number;

  ngOnInit(): void {
    this.session = savedSession();
    this.activeObservation = activeObservation();
    this.hasSavedSession.set(!!this.session);
    this.log.log('app_opened', {
      resumedSessionAvailable: !!this.session,
      online: navigator.onLine,
    });
    window.addEventListener('offline', this.onOffline);
    window.addEventListener('online', this.onOnline);
  }

  ngOnDestroy(): void {
    this.stopCamera();
    window.removeEventListener('offline', this.onOffline);
    window.removeEventListener('online', this.onOnline);
  }

  private onOffline = () => {
    this.progress.set('Offline · will retry uploads');
    this.log.log('offline');
  };
  private onOnline = () => {
    this.progress.set('Connected · resuming');
    this.log.log('online');
  };

  async start(resume = false): Promise<void> {
    this.phase.set('starting');
    this.error.set('');
    this.log.log('camera_preflight', {
      secureContext: window.isSecureContext,
      mediaDevices: !!navigator.mediaDevices,
      origin: location.origin,
    });
    if (!window.isSecureContext) {
      this.fail(
        'Camera access is blocked on LAN HTTP. Open the trusted HTTPS LAN address.',
        new Error('insecure_context'),
      );
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      this.fail(
        'This browser does not expose camera access.',
        new Error('media_devices_unavailable'),
      );
      return;
    }
    try {
      if (!resume || !this.session) {
        await clearStills();
        this.activeObservation = undefined;
        saveActiveObservation();
        this.lastFingerprint = undefined;
        this.captureCount = 0;
        this.scanNextSince = undefined;
        this.session = await this.api.create();
        saveSession(this.session);
        this.log.log('session_created', {
          sessionId: this.session.id,
          revision: this.session.revision,
        });
      } else {
        const state = await this.api.session(this.session);
        this.session.revision = state.revision;
        saveSession(this.session);
        this.setGuidance(state.guidance);
        this.log.log('session_resumed', {
          sessionId: this.session.id,
          revision: state.revision,
          stage: state.stage,
        });
      }
      await this.openCamera();
      this.phase.set('scanning');
      this.progress.set('Looking for a pattern');
      this.timer = window.setInterval(() => void this.tick(), 450);
      await this.refresh();
    } catch (cause) {
      this.fail(
        'Camera or session could not start. Check permission and connection, then retry.',
        cause,
      );
    }
  }

  private async openCamera(): Promise<void> {
    const video = this.preview?.nativeElement;
    if (!video) throw new Error('Camera preview is not mounted');
    this.camera = new CameraCapture(video);
    await this.camera.start();
    this.torchAttempted = false;
    this.torchAt = undefined;
    this.log.log('camera_started', {
      ...this.camera.dimensions(),
      settings: this.camera.track?.getSettings(),
      orientation: screen.orientation?.angle,
    });
    this.camera.track?.addEventListener('ended', () =>
      this.fail(
        'Camera disconnected. Reopen the session to continue.',
        new Error('camera_track_ended'),
      ),
    );
  }

  private stopCamera(): void {
    if (this.timer) window.clearInterval(this.timer);
    this.timer = undefined;
    this.camera?.stop();
    this.camera = undefined;
    this.log.log('camera_stopped');
  }

  private fail(message: string, cause: unknown): void {
    this.log.log('error', { message, cause: String(cause) });
    this.error.set(message);
    this.phase.set('error');
    this.stopCamera();
  }

  private setGuidance(guidance?: Guidance): void {
    if (!guidance) return;
    this.guidance.set(guidance);
    const action = [
      'move_left',
      'move_right',
      'move_up',
      'move_down',
      'tilt_left',
      'tilt_right',
    ].includes(guidance.action)
      ? 'show_full_pattern'
      : guidance.action;
    this.setCue(action);
    if (guidance.action === 'scan_next' && !this.scanNextSince) this.scanNextSince = Date.now();
    else if (guidance.action !== 'scan_next') this.scanNextSince = undefined;
    this.log.log('guidance', {
      action: guidance.action,
      displayedAction: action,
      target: guidance.target,
      reason: guidance.reason,
    });
  }

  private async refresh(): Promise<void> {
    if (!this.session) return;
    const [state, result] = await Promise.all([
      this.api.session(this.session),
      this.api.results(this.session),
    ]);
    if (state.revision >= this.session.revision) {
      this.session.revision = state.revision;
      saveSession(this.session);
      this.setGuidance(state.guidance);
      this.progress.set(
        `${state.observation_count} still${state.observation_count === 1 ? '' : 's'} analyzed`,
      );
    }
    this.results.set(result);
    this.log.log('session_refresh', {
      revision: state.revision,
      stage: state.stage,
      observations: state.observation_count,
      rows: result.rows.length,
      unresolved: result.unresolved.length,
    });
  }

  private async tick(): Promise<void> {
    if (this.tickBusy || !this.session || !this.camera || this.phase() === 'results') return;
    this.tickBusy = true;
    try {
      if (this.activeObservation) {
        await this.pollObservation();
        return;
      }
      if (this.guidance().action === 'complete' || this.guidance().action === 'stop') {
        await this.finishScan('server_complete');
        return;
      }
      const pending = await pendingStills();
      if (pending.length) {
        await this.upload(pending[0].key, pending[0].blob);
        return;
      }
      if (this.scanNextSince && Date.now() - this.scanNextSince > 20_000) {
        await this.finishScan('scan_next_timeout');
        return;
      }
      if (this.captureCount >= 20) {
        await this.finishScan('capture_limit');
        return;
      }
      const quality = this.camera.sample();
      if (!quality) return;
      if (quality.brightness < 55 && !this.torchAttempted) {
        this.torchAttempted = true;
        try {
          if (await this.camera.torch(true)) {
            this.torchAt = Date.now();
            this.torchBaseline = quality.brightness;
            this.log.log('torch_enabled', { brightness: quality.brightness });
          } else this.log.log('torch_unavailable');
        } catch (cause) {
          this.log.log('torch_failed', { cause: String(cause) });
        }
      }
      if (this.torchAt && Date.now() - this.torchAt > 2000) {
        const improved =
          quality.brightness > (this.torchBaseline ?? 0) + 12 && quality.brightness < 220;
        this.log.log('torch_assessed', {
          improved,
          before: this.torchBaseline,
          after: quality.brightness,
        });
        if (!improved) await this.camera.torch(false).catch(() => false);
        this.torchAt = undefined;
      }
      if (Date.now() - this.lastQualityLog > 4000) {
        this.log.log('frame_quality', {
          brightness: +quality.brightness.toFixed(1),
          motion: +quality.motion.toFixed(1),
          sharpness: +quality.sharpness.toFixed(1),
          reason: quality.reason,
        });
        this.lastQualityLog = Date.now();
      }
      this.metrics.set(
        `Sharpness ${quality.sharpness.toFixed(0)} · Light ${quality.brightness.toFixed(0)} · Motion ${quality.motion.toFixed(0)}`,
      );
      if (!quality.ready) {
        this.stableFrames = 0;
        this.showLocalCue(quality.reason === 'ready' ? 'hold_still' : quality.reason);
        return;
      }
      if (
        this.lastFingerprint &&
        fingerprintDistance(quality.fingerprint, this.lastFingerprint) < 7
      ) {
        this.stableFrames = 0;
        this.showLocalCue(this.guidance().action === 'scan_next' ? 'show_full_pattern' : 'closer');
        return;
      }
      this.stableFrames++;
      this.showLocalCue('hold_still');
      if (this.stableFrames < 3 || Date.now() - this.lastCaptureAt < 3000) return;
      await this.capture(quality);
    } catch (cause) {
      this.log.log('tick_failed', { cause: String(cause) });
      this.progress.set(
        navigator.onLine ? 'Waiting for server · retrying' : 'Offline · waiting to upload',
      );
    } finally {
      this.tickBusy = false;
    }
  }

  private showLocalCue(action: GuidanceAction): void {
    const requested = this.guidance().action;
    this.setCue(
      action === 'hold_still' && ['closer', 'farther', 'scan_next'].includes(requested)
        ? requested
        : action,
    );
  }

  private setCue(action: GuidanceAction): void {
    this.visualAction.set(action);
    this.cue.set(cues[action]);
  }

  private async capture(quality: Quality): Promise<void> {
    if (!this.session || !this.camera) return;
    this.stableFrames = 0;
    this.lastCaptureAt = Date.now();
    const still = await this.camera.takeStill();
    const key = crypto.randomUUID();
    await saveStill({ key, blob: still.blob, createdAt: Date.now() });
    this.captureCount++;
    this.lastFingerprint = quality.fingerprint;
    this.log.log('still_selected', {
      key,
      method: still.method,
      width: still.width,
      height: still.height,
      bytes: still.blob.size,
      captureCount: this.captureCount,
      guidance: this.guidance().action,
    });
    await this.upload(key, still.blob);
  }

  private async upload(key: string, blob: Blob): Promise<void> {
    if (!this.session || !navigator.onLine) return;
    this.phase.set('processing');
    this.progress.set('Analyzing this view');
    const result = await this.api.upload(this.session, blob, key);
    this.activeObservation = result.observation_id;
    saveActiveObservation(this.activeObservation);
    await removeStill(key);
    this.session.revision = Math.max(this.session.revision, result.revision);
    saveSession(this.session);
    this.log.log('still_uploaded', {
      key,
      observationId: this.activeObservation,
      status: result.status,
      revision: result.revision,
    });
  }

  private async pollObservation(): Promise<void> {
    if (!this.session || !this.activeObservation) return;
    const observation = await this.api.observation(this.session, this.activeObservation);
    if (observation.status === 'queued' || observation.status === 'processing') return;
    this.log.log('observation_finished', {
      observationId: this.activeObservation,
      status: observation.status,
      revision: observation.revision,
      error: observation.error,
    });
    this.activeObservation = undefined;
    saveActiveObservation();
    await this.refresh();
    this.phase.set('scanning');
    if (observation.status === 'failed')
      this.progress.set('Analysis could not finish · show another view');
  }

  private async finishScan(reason: string): Promise<void> {
    this.log.log('scan_finished', {
      reason,
      captures: this.captureCount,
      rows: this.results().rows.length,
    });
    this.stopCamera();
    try {
      await this.refresh();
    } catch (cause) {
      this.log.log('final_refresh_failed', { cause: String(cause) });
    }
    this.phase.set('results');
    this.progress.set(reason === 'scan_next_timeout' ? 'No new pattern found' : 'Scan finished');
  }

  async stop(): Promise<void> {
    await this.finishScan('user_stop');
  }
  async copy(): Promise<void> {
    if (!this.session) return;
    try {
      const output = await this.api.export(this.session);
      await navigator.clipboard.writeText(output.text ?? '');
      this.copied.set(true);
      this.log.log('export_copied', {
        rows: output.rows.length,
        conflicts: output.conflicts.length,
      });
    } catch (cause) {
      this.error.set(`Copy failed: ${String(cause)}`);
    }
  }
  async downloadDiagnostics(): Promise<void> {
    let server: unknown;
    try {
      if (this.session) server = await this.api.diagnostics(this.session);
    } catch (cause) {
      server = { error: String(cause) };
    }
    this.log.download(server);
  }
  async deleteSession(): Promise<void> {
    this.stopCamera();
    try {
      if (this.session) await this.api.delete(this.session);
    } catch (cause) {
      this.log.log('session_delete_failed', { cause: String(cause) });
      this.error.set('Could not delete the server session. Retry when connected.');
      return;
    }
    this.session = undefined;
    saveSession(undefined);
    saveActiveObservation();
    await clearStills();
    this.phase.set('welcome');
    this.hasSavedSession.set(false);
    this.log.log('session_deleted');
  }
}
