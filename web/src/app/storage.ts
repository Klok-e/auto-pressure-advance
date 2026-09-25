import { Session } from './api';

export type PendingStill = { key: string; blob: Blob; createdAt: number };
const sessionKey = 'adaptive-pa-session';
const observationKey = 'adaptive-pa-active-observation';
const databaseName = 'adaptive-pa-selected-stills';
const fallback = new Map<string, PendingStill>();

export function savedSession(): Session | undefined {
  try {
    const raw = localStorage.getItem(sessionKey);
    return raw ? (JSON.parse(raw) as Session) : undefined;
  } catch {
    return undefined;
  }
}

export function saveSession(session: Session | undefined): void {
  if (session) localStorage.setItem(sessionKey, JSON.stringify(session));
  else localStorage.removeItem(sessionKey);
}

export function activeObservation(): string | undefined {
  return localStorage.getItem(observationKey) ?? undefined;
}
export function saveActiveObservation(id?: string): void {
  if (id) localStorage.setItem(observationKey, id);
  else localStorage.removeItem(observationKey);
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('pending', { keyPath: 'key' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function transact<T>(
  mode: IDBTransactionMode,
  callback: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await database();
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = callback(db.transaction('pending', mode).objectStore('pending'));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

export async function pendingStills(): Promise<PendingStill[]> {
  try {
    return await transact('readonly', (store) => store.getAll());
  } catch {
    return [...fallback.values()];
  }
}
export async function saveStill(still: PendingStill): Promise<void> {
  const all = await pendingStills();
  if (all.length >= 12) throw new Error('Local still storage limit reached');
  try {
    await transact('readwrite', (store) => store.put(still));
  } catch {
    fallback.set(still.key, still);
  }
}
export async function removeStill(key: string): Promise<void> {
  fallback.delete(key);
  try {
    await transact('readwrite', (store) => store.delete(key));
  } catch {
    return;
  }
}
export async function clearStills(): Promise<void> {
  fallback.clear();
  try {
    await transact('readwrite', (store) => store.clear());
  } catch {
    return;
  }
}
