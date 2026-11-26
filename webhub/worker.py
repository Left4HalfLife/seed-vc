"""Only this child process imports the model code or owns GPU tensors."""

import os
from functools import partial
from types import SimpleNamespace

from .storage import downloaded, record_download, save_audio


def load_pipeline(model_id):
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable. Check the NVIDIA driver and Container Toolkit.")
    if model_id == "style":
        import app_vc_v2 as model

        wrapper = model.load_models(SimpleNamespace(ar_checkpoint_path=None, cfm_checkpoint_path=None, compile=False))
        return partial(wrapper.convert_voice_with_streaming, device=model.device, dtype=model.dtype)

    if model_id == "speech":
        import app_vc as model
    elif model_id == "singing":
        import app_svc as model
    else:
        raise ValueError(f"Unknown model: {model_id}")
    model.device = torch.device("cuda")
    model.initialize(SimpleNamespace(checkpoint=None, config=None, fp16=True))
    return model.voice_conversion


def run(model_id, cache, outputs, conn, loader=load_pipeline):
    try:
        # Set these before importing any HF/transformers modules (spawn, not fork).
        cache.mkdir(parents=True, exist_ok=True)
        os.environ.update(HF_HUB_CACHE=str(cache), HF_HOME=str(cache.parent),
                          SEEDVC_CHECKPOINT_DIR=str(cache))
        if downloaded(cache):
            os.environ["HF_HUB_OFFLINE"] = "1"
        convert = loader(model_id)
        record_download(cache)
        conn.send(("ready", None))
        while True:
            try:
                args = conn.recv()
            except EOFError:
                return
            for chunk, audio in convert(*args):
                path = save_audio(outputs, model_id, audio) if audio is not None else None
                conn.send(("audio", (chunk, path)))
            conn.send(("done", None))
    except Exception as exc:
        # Report to the UI, then let multiprocessing log the full traceback.
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
        raise
    finally:
        conn.close()
