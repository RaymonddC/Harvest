"""Document store. MemoryStore for local runs and tests, FirestoreStore in the cloud.

Both expose the same small API; documents are plain dicts and every returned
document carries its id under "id".
"""

from __future__ import annotations

import copy
import threading
import uuid
from typing import Callable, Protocol

COLLECTIONS = (
    "farmers", "calls", "harvests", "forecast", "offers", "limits", "rival_quotes", "campaigns",
)

Listener = Callable[[str, str], None]


class Store(Protocol):
    supports_listeners: bool

    def get(self, coll: str, doc_id: str) -> dict | None: ...
    def list(self, coll: str) -> list[dict]: ...
    def set(self, coll: str, doc_id: str, data: dict, merge: bool = False) -> None: ...
    def add(self, coll: str, data: dict) -> str: ...
    def delete(self, coll: str, doc_id: str) -> None: ...
    def clear(self, coll: str) -> None: ...
    def subscribe(self, listener: Listener) -> Callable[[], None]: ...


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class MemoryStore:
    supports_listeners = True

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {c: {} for c in COLLECTIONS}
        self._lock = threading.RLock()
        self._listeners: list[Listener] = []

    def _notify(self, coll: str, doc_id: str) -> None:
        for listener in list(self._listeners):
            listener(coll, doc_id)

    def get(self, coll: str, doc_id: str) -> dict | None:
        with self._lock:
            doc = self._data.setdefault(coll, {}).get(doc_id)
            return {**copy.deepcopy(doc), "id": doc_id} if doc is not None else None

    def list(self, coll: str) -> list[dict]:
        with self._lock:
            return [{**copy.deepcopy(d), "id": k} for k, d in self._data.setdefault(coll, {}).items()]

    def set(self, coll: str, doc_id: str, data: dict, merge: bool = False) -> None:
        data = {k: v for k, v in copy.deepcopy(data).items() if k != "id"}
        with self._lock:
            docs = self._data.setdefault(coll, {})
            if merge and doc_id in docs:
                docs[doc_id].update(data)
            else:
                docs[doc_id] = data
        self._notify(coll, doc_id)

    def add(self, coll: str, data: dict) -> str:
        doc_id = new_id(coll[:-1] if coll.endswith("s") else coll)
        self.set(coll, doc_id, data)
        return doc_id

    def delete(self, coll: str, doc_id: str) -> None:
        with self._lock:
            self._data.setdefault(coll, {}).pop(doc_id, None)
        self._notify(coll, doc_id)

    def clear(self, coll: str) -> None:
        with self._lock:
            self._data[coll] = {}
        self._notify(coll, "*")

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None


class FirestoreStore:
    """Thin wrapper over google-cloud-firestore. The dashboard listens to Firestore directly."""

    supports_listeners = False

    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore

        self._db = firestore.Client(project=project)

    def get(self, coll: str, doc_id: str) -> dict | None:
        snap = self._db.collection(coll).document(doc_id).get()
        return {**snap.to_dict(), "id": snap.id} if snap.exists else None

    def list(self, coll: str) -> list[dict]:
        return [{**s.to_dict(), "id": s.id} for s in self._db.collection(coll).stream()]

    def set(self, coll: str, doc_id: str, data: dict, merge: bool = False) -> None:
        data = {k: v for k, v in data.items() if k != "id"}
        self._db.collection(coll).document(doc_id).set(data, merge=merge)

    def add(self, coll: str, data: dict) -> str:
        doc_id = new_id(coll[:-1] if coll.endswith("s") else coll)
        self.set(coll, doc_id, data)
        return doc_id

    def delete(self, coll: str, doc_id: str) -> None:
        self._db.collection(coll).document(doc_id).delete()

    def clear(self, coll: str) -> None:
        batch = self._db.batch()
        count = 0
        for snap in self._db.collection(coll).stream():
            batch.delete(snap.reference)
            count += 1
            if count % 400 == 0:
                batch.commit()
                batch = self._db.batch()
        batch.commit()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        return lambda: None


def make_store(backend: str, project: str | None = None) -> Store:
    if backend == "firestore":
        return FirestoreStore(project)
    return MemoryStore()
