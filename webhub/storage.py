"""Inventory the actual Hugging Face cache, independent of worker lifetime."""

import fcntl
import json
import os
from pathlib import Path
from uuid import uuid4


def snapshots(cache):
    return {
        str(path.relative_to(cache)): path.stat().st_size
        for path in cache.glob("models--*/snapshots/*/**/*")
        if path.is_file()
    }


def record_download(cache):
    files = snapshots(cache)
    if not files:
        raise RuntimeError("The model loaded without any files in its managed cache")
    manifest = cache.parent / "download.json"
    tmp = manifest.with_suffix(".tmp")
    tmp.write_text(json.dumps(files))
    tmp.replace(manifest)


def downloaded(cache):
    try:
        files = json.loads((cache.parent / "download.json").read_text())
        return bool(files) and all((cache / name).stat().st_size == size for name, size in files.items())
    except FileNotFoundError:
        return False


def transfer_active(cache, blob):
    # A .incomplete file can survive a killed download. The Hub's held blob
    # lock distinguishes an actual transfer from bytes left for a later retry.
    lock = cache / ".locks" / blob.parent.parent.name / (blob.stem + ".lock")
    try:
        with lock.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except FileNotFoundError:
        pass
    return False


def inventory(cache, loading):
    size = 0
    transfers = []
    artifacts = []
    for directory, _, names in os.walk(cache):
        for name in names:
            path = Path(directory, name)
            try:
                length = path.stat().st_size
            except FileNotFoundError:  # a completed download was just renamed
                continue
            parts = path.relative_to(cache).parts
            if len(parts) >= 4 and parts[1] == "snapshots":
                repo = parts[0].removeprefix("models--").replace("--", "/")
                artifacts.append({"file": f"{repo}/{'/'.join(parts[3:])}", "bytes": length})
            if path.is_symlink():  # HF snapshot entries point back to blobs
                continue
            size += length
            if loading and name.endswith(".incomplete") and transfer_active(cache, path):
                repo = path.parent.parent.name.removeprefix("models--").replace("--", "/")
                transfers.append({"repo": repo, "bytes": length})
    if transfers:
        state = "downloading"
    elif downloaded(cache):
        state = "downloaded"
    else:
        state = "partial" if size else "not downloaded"
    return {"download": state, "disk_bytes": size, "transfers": transfers,
            "files": sorted(artifacts, key=lambda a: a["file"])}


def save_audio(outputs, model_id, audio):
    import soundfile as sf

    rate, samples = audio
    path = outputs / f"{model_id}-{uuid4().hex}.wav"
    tmp = path.with_suffix(".part")
    try:
        sf.write(tmp, samples, rate, format="WAV")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return str(path)
