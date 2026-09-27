<div align="center">

<img src="src-tauri/icons/128x128.png" alt="AutoClip" width="80" height="80">

# AutoClip

**AI-powered long-form video clipping for upload-ready Shorts.**

Find complete, high-value moments in long videos, score them for short-form structure, and automatically render platform-ready vertical clips with captions and hooks.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-356%20passed-brightgreen.svg)](#development)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)

**Fork parent:** [Waishnav/devspace](https://github.com/Waishnav/devspace)

</div>

## What is AutoClip?

AutoClip is a local-first AI video clipping pipeline designed to turn long-form videos into publishable short-form content.

The current pipeline is built around:

```
Long video
   ↓
Import / transcription
   ↓
Content understanding
   ↓
Candidate moments
   ↓
Short-form scoring
   ↓
Complete-thought quality gate
   ↓
Short candidate selection
   ↓
Vertical composition
   ↓
Word-level captions + visual hook
   ↓
Upload-ready Shorts export
```

The goal is not simply to find interesting sentences. AutoClip tries to find **self-contained moments with a natural entry point, development, payoff, and ending**, then package them without unnecessary visual noise.

## Current capabilities

- **Local video processing** with Docker and FFmpeg.
- **YouTube and local video import** workflows.
- **Local Whisper transcription** through faster-whisper.
- **Automatic GPU detection** for CUDA-capable systems, with CPU fallback.
- **Candidate-moment scoring** with hook, context, development, payoff, ending, emotional, educational, and duration signals.
- **Strict Short quality gates** that reject incomplete thoughts and invalid short ranges before automatic publishing.
- **Automatic Short selection** separate from raw clip generation.
- **9:16 Shorts rendering** at 1080×1920.
- **Word-level karaoke captions** using actual Whisper word timestamps.
- **Caption normalization and safe-zone handling**.
- **Already-captioned vertical source mitigation** to avoid duplicated subtitle layers.
- **Short visual hooks** separated from platform metadata titles.
- **Automatic final exports** to `output/exports`.
- **Dockerized Web UI, API, Celery worker, and Redis**.
- **CLI pipeline execution** for automation and batch workflows.

## Short-form quality architecture

AutoClip currently separates content quality from rendering quality.

### Content selection

The system evaluates:

- Hook
- Standalone context
- Entry point
- Context
- Development
- Payoff
- Ending
- Emotional resonance
- Educational value
- Duration fit
- Complete-thought validity

The strongest candidates are selected only after passing the Short quality gate.

### Rendering

For vertical Shorts, AutoClip provides:

- 1080×1920 output
- Smart source composition
- Safe caption placement
- Word-level karaoke timing
- Short visual hook overlay
- H.264/AAC output
- `+faststart` for web delivery

If the source is already vertical and contains burned-in captions, AutoClip avoids stacking a second generated caption layer.

## Virality / retention roadmap

AutoClip does **not** claim to predict virality. The roadmap focuses on measurable short-form signals that can later be validated against real audience performance.

Planned retention-oriented scoring includes:

- Scroll-stop score
- Curiosity-gap score
- Shareability score
- Rewatch / loop score
- Retention-aware candidate ranking
- Audience-performance feedback
- Performance-based model calibration
- Platform-specific retention profiles
- A/B export experiments

See [ROADMAP.md](ROADMAP.md) for the current backlog.

## Quick start

### 1. Clone

```bash
git clone https://github.com/SoloistHart/autoclip.git
cd autoclip
```

### 2. Configure environment

Copy the example configuration:

```bash
cp env.example .env
```

Never commit `.env`. API keys and local runtime configuration belong in the ignored environment file.

At minimum, configure an LLM provider and API key, or configure the provider through the application settings.

### 3. Start the application

```bash
docker compose up -d --build
```

Then open:

- Web UI: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

### GPU support

For NVIDIA GPU-enabled Whisper inference:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

AutoClip resolves Whisper to CUDA + FP16 when a compatible CUDA device is visible and falls back to CPU + INT8 otherwise.

The current tested GPU path uses an NVIDIA RTX 3050 Laptop GPU through Docker/WSL2.

## Project structure

```
backend/
  api/             FastAPI endpoints
  pipeline/        Multi-step clipping pipeline
  services/        Rendering, publishing, subtitles
  utils/           Whisper, video and shared utilities
  tests/           Automated test suite

frontend/
  src/             Web UI

prompt/
  ...              LLM prompt templates

data/
  ...              Local runtime data (ignored)

docker-compose.yml
docker-compose.gpu.yml
Dockerfile
ROADMAP.md
```

## Development

Run the backend test suite inside the application container:

```bash
docker compose exec -T autoclip pytest -q
```

The latest verified full suite for this working tree is **356 passed, 0 failed**.

Before pushing changes:

```bash
git diff --check
docker compose exec -T autoclip pytest -q
```

## Environment and secrets

The repository intentionally excludes:

- `.env` and local environment overrides
- API keys and credentials
- uploaded videos and generated media
- local project data
- runtime databases
- logs
- temporary API responses
- local CUDA libraries
- build and packaging artifacts
- local updater signing keys

Use [env.example](env.example) as the safe configuration template.

If a secret is ever committed accidentally, rotate the credential immediately; removing it from the latest commit does not make an exposed credential safe.

## Upstream and attribution

This repository is configured as a GitHub fork of [Waishnav/devspace](https://github.com/Waishnav/devspace).

The DevSpace project is licensed under MIT. AutoClip also retains its existing project license and attribution files where applicable.

## License

MIT. See [LICENSE](LICENSE).
