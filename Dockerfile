FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 GRADIO_ANALYTICS_ENABLED=False SEEDVC_DATA=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY webhub/requirements.txt /tmp/webhub-requirements.txt
RUN pip install --no-cache-dir -r /tmp/webhub-requirements.txt
# The official Linux x86_64 wheels on PyPI include CUDA 12.1 support.
RUN pip install --no-cache-dir torch==2.4.0 torchaudio==2.4.0

COPY LICENSE app_vc.py app_svc.py app_vc_v2.py hf_utils.py ./
COPY modules modules
COPY configs configs
COPY examples examples
COPY webhub webhub
EXPOSE 7860
CMD ["uvicorn", "webhub.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
