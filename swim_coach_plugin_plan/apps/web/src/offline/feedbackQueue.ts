import { api } from "../api/client";

export interface FeedbackPayload {
  rpe: number;
  technique_rating: number | null;
  fatigue_rating: number | null;
  enjoyment_rating: number | null;
  pain_present: boolean;
  pain_location: string | null;
  pain_intensity: number | null;
  comment: string | null;
  version: number | null;
}

interface QueuedFeedback {
  idempotencyKey: string;
  activityId: string;
  payload: FeedbackPayload;
  createdAt: string;
}

const DATABASE = "swim-coach-offline-v1";
const STORE = "feedback";

export async function saveFeedbackResilient(
  activityId: string,
  payload: FeedbackPayload,
): Promise<"synced" | "queued"> {
  const idempotencyKey = crypto.randomUUID();
  if (navigator.onLine) {
    try {
      await api.saveFeedback(activityId, idempotencyKey, payload);
      return "synced";
    } catch (error) {
      if (!(error instanceof TypeError)) throw error;
    }
  }
  for (const existing of await all()) {
    if (existing.activityId === activityId) await remove(existing.idempotencyKey);
  }
  await put({ idempotencyKey, activityId, payload, createdAt: new Date().toISOString() });
  window.dispatchEvent(new CustomEvent("swim-coach:feedback-queued"));
  return "queued";
}

export async function flushFeedbackQueue(): Promise<number> {
  if (!navigator.onLine) return 0;
  const items = await all();
  let flushed = 0;
  for (const item of items) {
    try {
      await api.saveFeedback(item.activityId, item.idempotencyKey, item.payload);
      await remove(item.idempotencyKey);
      flushed += 1;
    } catch (error) {
      if (error instanceof TypeError) break;
      // A validation or conflict response needs human reconciliation; retain it.
      window.dispatchEvent(
        new CustomEvent("swim-coach:feedback-conflict", {
          detail: { activityId: item.activityId },
        }),
      );
    }
  }
  if (flushed) window.dispatchEvent(new CustomEvent("swim-coach:feedback-flushed"));
  return flushed;
}

export async function clearFeedbackQueue(): Promise<void> {
  await transaction("readwrite", (store) => store.clear());
  window.dispatchEvent(new CustomEvent("swim-coach:feedback-cleared"));
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "idempotencyKey" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function transaction<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const request = operation(tx.objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

function put(item: QueuedFeedback): Promise<IDBValidKey> {
  return transaction("readwrite", (store) => store.put(item));
}

function all(): Promise<QueuedFeedback[]> {
  return transaction("readonly", (store) => store.getAll()) as Promise<QueuedFeedback[]>;
}

function remove(key: string): Promise<undefined> {
  return transaction("readwrite", (store) => store.delete(key)) as Promise<undefined>;
}
