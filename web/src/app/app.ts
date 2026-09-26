import { CommonModule } from '@angular/common';
import {
  Component,
  computed,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
  signal,
} from '@angular/core';
import {
  Api,
  Guidance,
  GuidanceAction,
  GuidanceTarget,
  InspectionProgress,
  Results,
  Session,
} from './api';
import { CameraCapture, fingerprintDistance, measureEnlargement, Quality } from './camera';
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

type VisualAction = GuidanceAction | 'change_angle' | 'focus' | 'brace';
type Activity =
  'framing' | 'steadying' | 'capturing' | 'uploading' | 'queued' | 'analyzing' | 'retrying';
const phaseLabels: Record<string, string> = {
  locate: 'Finding the pattern',
  identify: 'Recognizing the pattern',
  metadata: 'Reading printed settings',
  candidate: 'Comparing the corners',
  verify: 'Checking a second view',
};
const CAPTURE_STABLE_FRAMES = 2;
const cues: Record<VisualAction, { icon: string; label: string }> = {
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
  change_angle: { icon: '↷', label: 'Show another angle' },
  focus: { icon: '◎', label: 'Let the camera focus' },
  brace: { icon: '⊥', label: 'Brace your phone' },
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
  readonly visualAction = signal<VisualAction>('show_full_pattern');
  readonly guidance = signal<Guidance>({ action: 'show_full_pattern' });
  readonly results = signal<Results>({ revision: 0, rows: [], unresolved: [], conflicts: [] });
  readonly error = signal('');
  readonly progress = signal('Ready');
  readonly hasSavedSession = signal(false);
  readonly copied = signal(false);
  readonly expandedDetails = signal(false);
  readonly activity = signal<Activity>('framing');
  readonly steadyProgress = signal(0);
  readonly elapsed = signal(0);
  readonly inspectionPhase = signal('identify');
  readonly inspectingDetail = signal(false);
  readonly inspection = signal<
    { marked: string; detail: string; target: GuidanceTarget } | undefined
  >(undefined);
  readonly inspectionLoading = signal(false);
  readonly inspectionError = signal(false);
  readonly stageIndex = computed(() =>
    ['identify', 'metadata', 'candidate', 'verify'].indexOf(this.inspectionPhase()),
  );
  readonly statusTitle = computed(() => {
    switch (this.activity()) {
      case 'steadying':
        return 'Steady for photo';
      case 'capturing':
        return 'Taking photo…';
      case 'uploading':
        return 'Photo saved · sending';
      case 'queued':
        return 'Photo queued';
      case 'analyzing':
        return this.inspectingDetail()
          ? 'Inspecting marked area'
          : (phaseLabels[this.inspectionPhase()] ?? 'Inspecting photo');
      case 'retrying':
        return navigator.onLine ? 'Reconnecting…' : 'Photo saved · offline';
      default:
        return this.visualAction() === 'closer' && this.inspection()
          ? 'Closer to marked area'
          : this.cue().label;
    }
  });
  readonly statusDetail = computed(() => {
    if (this.activity() === 'analyzing' || this.activity() === 'queued')
      return `Photo captured · ${this.elapsed()}s${this.elapsed() >= 15 ? ' · still working' : ''}`;
    if (this.activity() === 'capturing') return 'Automatic photo · no tap needed';
    if (this.activity() === 'uploading') return `${this.elapsed()}s · you can relax your hands`;
    if (this.activity() === 'steadying') return 'Captures automatically when the ring fills';
    return this.progress();
  });
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
  private lastCaptureFraming?: Uint8Array;
  private closerReference?: Uint8Array;
  private closerRequested = false;
  private lastCloserLog = 0;
  private lastQualityLog = 0;
  private scanNextSince?: number;
  private activeObservation?: string;
  private torchAttempted = false;
  private torchAt?: number;
  private torchBaseline?: number;
  private activityAt = Date.now();
  private gateReason = '';
  private gateSince = 0;
  private inspectionKey = '';
  private inspectionRetryAt = 0;
  private run = 0;

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
    this.clearInspection();
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
    this.stopCamera();
    this.clearInspection();
    this.stableFrames = 0;
    this.steadyProgress.set(0);
    this.gateReason = '';
    this.setActivity('framing');
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
        this.guidance.set({ action: 'show_full_pattern' });
        this.inspectionPhase.set('identify');
        this.setCue('show_full_pattern');
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
      this.timer = window.setInterval(() => {
        this.elapsed.set(Math.max(0, Math.floor((Date.now() - this.activityAt) / 1000)));
        void this.tick();
      }, 450);
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
    this.run++;
    if (this.timer) window.clearInterval(this.timer);
    this.timer = undefined;
    this.camera?.stop();
    this.camera = undefined;
    this.closerReference = undefined;
    this.closerRequested = false;
    this.lastCaptureFraming = undefined;
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
    if (guidance.action === 'closer') {
      if (!this.closerRequested) {
        this.closerReference = this.lastCaptureFraming;
        this.lastCloserLog = 0;
      }
      this.closerRequested = true;
    } else {
      this.closerRequested = false;
      this.closerReference = undefined;
    }
    this.guidance.set(guidance);
    if (guidance.phase) this.inspectionPhase.set(guidance.phase);
    this.progress.set(guidance.reason || 'Fit one whole V-shaped print in the camera');
    void this.showInspection(guidance.target);
    const action: VisualAction = [
      'move_left',
      'move_right',
      'move_up',
      'move_down',
      'tilt_left',
      'tilt_right',
    ].includes(guidance.action)
      ? 'show_full_pattern'
      : guidance.phase === 'verify' && guidance.action === 'show_full_pattern'
        ? 'change_angle'
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
    }
    this.results.set(result);
    this.log.log('session_refresh', {
      revision: state.revision,
      stage: state.stage,
      observations: state.observation_count,
      rows: result.rows.length,
      unresolved: result.unresolved.length,
      agentSteps: state.patterns.map((pattern) => ({
        patternId: pattern['id'],
        phase: pattern['agent_phase'],
        status: pattern['status'],
        attempts: pattern['attempts'],
        reason: pattern['reason'],
      })),
    });
  }

  private async tick(): Promise<void> {
    if (this.tickBusy || !this.session || !this.camera || this.phase() === 'results') return;
    const run = this.run;
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
      if (run !== this.run) return;
      if (pending.length) {
        await this.upload(pending[0].key, pending[0].blob);
        return;
      }
      this.phase.set('scanning');
      if (this.inspectionError()) void this.showInspection(this.guidance().target);
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
          rawMotion: +quality.rawMotion.toFixed(1),
          sharpness: +quality.sharpness.toFixed(1),
          reason: quality.reason,
        });
        this.lastQualityLog = Date.now();
      }
      if (!quality.ready) {
        this.stableFrames = 0;
        this.steadyProgress.set(0);
        this.waitForView(quality.reason, quality);
        return;
      }
      if (this.closerRequested) {
        // An explicit restart has no capture reference; require enlargement from its first ready view.
        this.closerReference ??= quality.framing;
        const enlargement = measureEnlargement(this.closerReference, quality.framing);
        if (Date.now() - this.lastCloserLog > 4000 || (enlargement.ready && !this.stableFrames)) {
          this.log.log('closer_gate', {
            requestedAction: this.guidance().action,
            state: enlargement.ready ? 'enlarged' : 'waiting',
            scale: +enlargement.scale.toFixed(2),
            correlation: +enlargement.correlation.toFixed(3),
            separation: +enlargement.separation.toFixed(3),
            minimumScale: 1.18,
            minimumCorrelation: 0.8,
            minimumSeparation: 0.05,
          });
          this.lastCloserLog = Date.now();
        }
        if (!enlargement.ready) {
          this.stableFrames = 0;
          this.steadyProgress.set(0);
          this.waitForView('closer', quality);
          return;
        }
      }
      if (
        !this.closerRequested &&
        this.lastFingerprint &&
        fingerprintDistance(quality.fingerprint, this.lastFingerprint) < 7
      ) {
        this.stableFrames = 0;
        this.steadyProgress.set(0);
        this.waitForView('unchanged', quality);
        return;
      }
      this.gateReason = '';
      this.stableFrames++;
      this.steadyProgress.set(Math.min(1, this.stableFrames / CAPTURE_STABLE_FRAMES));
      this.setActivity('steadying');
      this.setCue('hold_still');
      if (this.stableFrames < CAPTURE_STABLE_FRAMES || Date.now() - this.lastCaptureAt < 3000)
        return;
      await this.capture(quality);
    } catch (cause) {
      if (run !== this.run) return;
      this.log.log('tick_failed', { cause: String(cause) });
      this.setActivity('retrying');
      this.progress.set(
        navigator.onLine ? 'Waiting for server · retrying' : 'Offline · waiting to upload',
      );
    } finally {
      this.tickBusy = false;
    }
  }

  private waitForView(reason: Quality['reason'] | 'unchanged' | 'closer', quality: Quality): void {
    if (this.gateReason !== reason) {
      const now = Date.now();
      this.log.log('capture_wait', {
        reason,
        previousReason: this.gateReason,
        previousWaitMs: this.gateReason && this.gateSince ? now - this.gateSince : 0,
        motion: quality.motion,
        rawMotion: quality.rawMotion,
        sharpness: quality.sharpness,
        brightness: quality.brightness,
        requestedAction: this.guidance().action,
        requestedReason: this.guidance().reason,
      });
      this.gateReason = reason;
      this.gateSince = now;
    }
    const waiting = Date.now() - this.gateSince;
    this.setActivity('framing');
    if (reason === 'closer') {
      this.setCue('closer');
      this.progress.set('Bring the phone closer so the same print looks larger · keep it in view');
    } else if (reason === 'unchanged') {
      const requested = this.guidance();
      this.setCue(
        requested.phase === 'verify' || requested.action === 'hold_still'
          ? 'change_angle'
          : requested.action,
      );
      this.progress.set(requested.reason || 'Show a slightly different view of this print');
    } else if (reason === 'focus') {
      this.setCue('focus');
      this.progress.set(
        waiting > 3000
          ? 'Still blurry · back up a little to help focus'
          : 'Pause briefly while the camera focuses',
      );
    } else if (reason === 'improve_lighting') {
      this.setCue('improve_lighting');
      this.progress.set(
        quality.brightness > 220 ? 'Tilt away from glare' : 'Bring the print into even light',
      );
    } else {
      this.setCue(waiting > 4000 ? 'brace' : 'hold_still');
      this.progress.set(
        waiting > 4000
          ? 'Rest your elbows or support the phone'
          : 'Waiting for a sharp, steady moment',
      );
    }
  }

  private setCue(action: VisualAction): void {
    this.visualAction.set(action);
    this.cue.set(cues[action]);
  }

  private setActivity(activity: Activity, startedAt?: number): void {
    if (this.activity() === activity && (startedAt === undefined || this.activityAt === startedAt))
      return;
    this.log.log('camera_activity', {
      from: this.activity(),
      to: activity,
      elapsedMs: Date.now() - this.activityAt,
    });
    this.activity.set(activity);
    this.activityAt = startedAt ?? Date.now();
    this.elapsed.set(Math.max(0, Math.floor((Date.now() - this.activityAt) / 1000)));
  }

  private showAnalysis(progress: InspectionProgress): void {
    if (
      this.inspectionPhase() !== progress.phase ||
      this.inspectingDetail() !== (progress.activity === 'inspecting')
    ) {
      this.log.log('analysis_progress', {
        phase: progress.phase,
        activity: progress.activity,
        target: progress.target,
      });
    }
    this.inspectionPhase.set(progress.phase);
    this.inspectingDetail.set(progress.activity === 'inspecting');
    this.setActivity('analyzing', progress.started_at * 1000);
    void this.showInspection(progress.target);
  }

  private clearInspection(): void {
    this.inspectionKey = '';
    this.inspectionRetryAt = 0;
    const previous = this.inspection();
    if (previous) {
      URL.revokeObjectURL(previous.marked);
      URL.revokeObjectURL(previous.detail);
    }
    this.inspection.set(undefined);
    this.inspectionLoading.set(false);
    this.inspectionError.set(false);
  }

  private async showInspection(target?: GuidanceTarget | null): Promise<void> {
    if (!target || !this.session) {
      this.clearInspection();
      return;
    }
    const key = `${this.session.id}/${target.observation_id}/${target.inspection_index}`;
    if (
      this.inspectionKey === key &&
      (this.inspectionLoading() || this.inspection() || Date.now() < this.inspectionRetryAt)
    )
      return;
    this.clearInspection();
    this.inspectionKey = key;
    this.inspectionLoading.set(true);
    try {
      const [marked, detail] = await Promise.all([
        this.api.inspection(this.session, target, 'marked'),
        this.api.inspection(this.session, target, 'detail'),
      ]);
      if (this.inspectionKey !== key) return;
      this.inspection.set({
        marked: URL.createObjectURL(marked),
        detail: URL.createObjectURL(detail),
        target,
      });
      this.log.log('inspection_displayed', { ...target });
    } catch (cause) {
      if (this.inspectionKey !== key) return;
      this.inspectionRetryAt = Date.now() + 5000;
      this.inspectionError.set(true);
      this.log.log('inspection_display_failed', { cause: String(cause), ...target });
    } finally {
      if (this.inspectionKey === key) this.inspectionLoading.set(false);
    }
  }

  private async capture(quality: Quality): Promise<void> {
    if (!this.session || !this.camera) return;
    const run = this.run;
    this.phase.set('processing');
    this.setActivity('capturing');
    this.stableFrames = 0;
    this.lastCaptureAt = Date.now();
    this.log.log('capture_started', {
      requestedAction: this.guidance().action,
      sharpness: quality.sharpness,
      motion: quality.motion,
      rawMotion: quality.rawMotion,
      requiredStableFrames: CAPTURE_STABLE_FRAMES,
    });
    const still = await this.camera.takeStill();
    if (run !== this.run) return;
    const key = crypto.randomUUID();
    await saveStill({ key, blob: still.blob, createdAt: Date.now() });
    if (run !== this.run) return;
    this.captureCount++;
    this.lastFingerprint = quality.fingerprint;
    this.lastCaptureFraming = quality.framing;
    this.closerRequested = false;
    this.closerReference = undefined;
    this.log.log('still_selected', {
      key,
      method: still.method,
      fallback: still.fallback,
      captureMs: Date.now() - this.lastCaptureAt,
      width: still.width,
      height: still.height,
      bytes: still.blob.size,
      captureCount: this.captureCount,
      guidance: this.guidance().action,
    });
    await this.upload(key, still.blob);
  }

  private async upload(key: string, blob: Blob): Promise<void> {
    if (!this.session) return;
    this.phase.set('processing');
    if (!navigator.onLine) {
      this.setActivity('retrying');
      this.progress.set('Will send automatically when connected');
      return;
    }
    const run = this.run;
    this.setActivity('uploading');
    const startedAt = Date.now();
    const result = await this.api.upload(this.session, blob, key);
    if (run !== this.run) return;
    this.activeObservation = result.observation_id;
    saveActiveObservation(this.activeObservation);
    await removeStill(key);
    this.session.revision = Math.max(this.session.revision, result.revision);
    saveSession(this.session);
    this.log.log('still_uploaded', {
      uploadMs: Date.now() - startedAt,
      key,
      observationId: this.activeObservation,
      status: result.status,
      revision: result.revision,
    });
    this.setActivity('queued');
    this.clearInspection();
  }

  private async pollObservation(): Promise<void> {
    if (!this.session || !this.activeObservation) return;
    const run = this.run;
    const observation = await this.api.observation(this.session, this.activeObservation);
    if (run !== this.run) return;
    if (observation.status === 'queued' || observation.status === 'processing') {
      this.phase.set('processing');
      if (observation.progress) this.showAnalysis(observation.progress);
      else this.setActivity(observation.status === 'queued' ? 'queued' : 'analyzing');
      return;
    }
    this.log.log('observation_finished', {
      observationId: this.activeObservation,
      status: observation.status,
      revision: observation.revision,
      error: observation.error,
    });
    this.activeObservation = undefined;
    saveActiveObservation();
    await this.refresh();
    if (run !== this.run) return;
    this.camera?.resetMotion();
    this.stableFrames = 0;
    this.steadyProgress.set(0);
    this.gateReason = '';
    this.setActivity('framing');
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
    this.clearInspection();
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
