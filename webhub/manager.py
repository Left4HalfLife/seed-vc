import multiprocessing
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from threading import RLock

from . import worker
from .storage import inventory

MODELS = {
    "speech": ("Voice conversion", "V1 · 22 kHz", "Transfer a reference voice to recorded speech."),
    "singing": ("Singing conversion", "V1 · 44 kHz", "Convert vocals with pitch tracking and semitone controls."),
    "style": ("Voice & style", "V2 · 22 kHz", "Convert timbre, accent or emotion, or anonymize a voice."),
}


class Busy(RuntimeError):
    pass


@dataclass
class Slot:
    cache: Path
    process: multiprocessing.Process | None = None
    conn: Connection | None = None
    state: str = "unloaded"
    error: str | None = None
    busy: bool = False

    def stop(self, error=None):
        if self.process is not None:
            self.process.terminate()
            self.process.join(timeout=3)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            self.process.close()
            self.conn.close()
            self.process = self.conn = None
        self.state = "error" if error else "unloaded"
        self.error = error

    def refresh(self):
        if self.process is None:
            return
        if self.state == "loading" and self.conn.poll():
            try:
                tag, detail = self.conn.recv()
            except (EOFError, OSError):
                self.stop("Worker exited before loading finished; check container logs.")
                return
            if tag != "ready":
                self.stop(detail)
                return
            self.state = "loaded"
        if not self.process.is_alive() and not self.busy:
            self.stop(f"Worker exited (code {self.process.exitcode}); check container logs.")


class Manager:
    def __init__(self, data, loader=worker.load_pipeline):
        self.outputs = data / "outputs"
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.slots = {key: Slot(data / "models" / key / "hub") for key in MODELS}
        self.loader = loader
        self.lock = RLock()
        self.context = multiprocessing.get_context("spawn")

    def load(self, key):
        with self.lock:
            slot = self.slots[key]
            slot.refresh()
            if slot.process is None and not slot.busy:
                parent, child = self.context.Pipe()
                process = self.context.Process(target=worker.run, daemon=True,
                                               args=(key, slot.cache, self.outputs, child, self.loader))
                try:
                    process.start()
                except OSError:
                    parent.close()
                    raise
                finally:
                    child.close()
                slot.process, slot.conn, slot.state, slot.error = process, parent, "loading", None
            return slot.state

    def unload(self, key=None, *, shutdown=False):
        with self.lock:
            slots = list(self.slots.values()) if key is None else [self.slots[key]]
            if not shutdown and any(slot.busy for slot in slots):
                raise Busy("Conversion in progress; retry unloading after it finishes.")
            for slot in slots:
                slot.stop()

    def status(self):
        result = []
        for key, slot in self.slots.items():
            with self.lock:
                slot.refresh()
                state, busy, error = slot.state, slot.busy, slot.error
            result.append({"id": key, "state": state, "busy": busy, "error": error,
                           **inventory(slot.cache, state == "loading")})
        return result

    def convert(self, key, *args):
        with self.lock:
            slot = self.slots[key]
            if slot.busy:
                raise Busy("This model is already converting audio.")
            self.load(key)
            slot.busy = True
        finished = False
        try:
            while True:
                with self.lock:
                    slot.refresh()
                    if slot.state != "loading":
                        if slot.state != "loaded":
                            raise RuntimeError(slot.error or "Model unloaded.")
                        break
                time.sleep(0.1)
            slot.conn.send(args)
            while True:
                tag, data = slot.conn.recv()
                if tag == "done":
                    finished = True
                    return
                if tag == "error":
                    raise RuntimeError(data)
                yield data
        except (EOFError, OSError) as exc:
            message = "Worker disconnected; check container logs."
            with self.lock:
                slot.stop(message)
            raise RuntimeError(message) from exc
        except RuntimeError as exc:
            with self.lock:
                slot.stop(str(exc))
            raise
        finally:
            with self.lock:
                # On client cancellation discard unread chunks and release the
                # worker instead of feeding an old response to the next caller.
                if not finished and slot.process is not None:
                    slot.stop()
                slot.busy = False
