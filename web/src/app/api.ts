import type { components } from './api.generated';

type Schema = components['schemas'];
export type GuidanceAction = Schema['Guidance']['action'];
export type Guidance = Schema['Guidance'];
export type GuidanceTarget = Schema['GuidanceTarget'];
export type InspectionProgress = Schema['InspectionProgress'];
export type Session = Schema['CreatedSession'];
export type SessionState = Schema['SessionState'];
export type Observation = Schema['ObservationState'] | Schema['QueuedObservation'];
export type Results = Schema['ResultsState'] & Partial<Pick<Schema['ExportState'], 'text'>>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export class Api {
  constructor(readonly base = '') {}

  private async request<T>(path: string, options: RequestInit = {}, secret?: string): Promise<T> {
    const headers = new Headers(options.headers);
    if (secret) headers.set('X-Session-Secret', secret);
    const response = await fetch(`${this.base}/api${path}`, {
      ...options,
      headers,
      cache: 'no-store',
    });
    if (!response.ok) {
      let data: { detail?: unknown; code?: string; message?: string } = {};
      try {
        data = await response.json();
      } catch {
        /* use HTTP status */
      }
      const nested =
        data.detail && typeof data.detail === 'object' && !Array.isArray(data.detail)
          ? (data.detail as { code?: string; message?: string })
          : undefined;
      const detail =
        typeof data.detail === 'string'
          ? data.detail
          : (nested?.message ?? data.message ?? response.statusText);
      throw new ApiError(
        response.status,
        nested?.code ?? data.code ?? `http_${response.status}`,
        detail,
      );
    }
    return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>);
  }

  create(): Promise<Session> {
    return this.request('/sessions', { method: 'POST' });
  }
  session(session: Session): Promise<SessionState> {
    return this.request(`/sessions/${encodeURIComponent(session.id)}`, {}, session.access_secret);
  }
  guidance(session: Session): Promise<Schema['GuidanceState']> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}/guidance`,
      {},
      session.access_secret,
    );
  }
  results(session: Session): Promise<Results> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}/results`,
      {},
      session.access_secret,
    );
  }
  export(session: Session): Promise<Results> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}/export`,
      { method: 'POST' },
      session.access_secret,
    );
  }
  diagnostics(session: Session): Promise<Schema['DiagnosticsState']> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}/diagnostics`,
      {},
      session.access_secret,
    );
  }
  cancel(session: Session): Promise<unknown> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}/cancel`,
      { method: 'POST' },
      session.access_secret,
    );
  }
  delete(session: Session): Promise<void> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}`,
      { method: 'DELETE' },
      session.access_secret,
    );
  }
  observation(session: Session, id: string): Promise<Schema['ObservationState']> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}/observations/${encodeURIComponent(id)}`,
      {},
      session.access_secret,
    );
  }
  async inspection(
    session: Session,
    target: GuidanceTarget,
    kind: 'marked' | 'detail',
  ): Promise<Blob> {
    const response = await fetch(
      `${this.base}/api/sessions/${encodeURIComponent(session.id)}/observations/${encodeURIComponent(target.observation_id)}/inspection/${target.inspection_index}/${kind}`,
      {
        headers: { 'X-Session-Secret': session.access_secret },
        cache: 'no-store',
        signal: AbortSignal.timeout(15_000),
      },
    );
    if (!response.ok)
      throw new ApiError(response.status, 'inspection_unavailable', 'Marked photo unavailable');
    return response.blob();
  }
  upload(session: Session, image: Blob, key: string): Promise<Schema['QueuedObservation']> {
    return this.request(
      `/sessions/${encodeURIComponent(session.id)}/observations`,
      {
        method: 'POST',
        body: image,
        headers: { 'Content-Type': image.type || 'image/jpeg', 'X-Idempotency-Key': key },
      },
      session.access_secret,
    );
  }
}
