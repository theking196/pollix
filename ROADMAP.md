# Pollix Upgrade Roadmap

Pollix is moving from a project-aware text CLI into a fuller Pollinations developer workbench.
This roadmap keeps the direction explicit while features are added incrementally.

## Direction

Pollix should expose Pollinations capabilities through safe, scriptable CLI workflows:

- richer text chat and code workflows,
- live model discovery and model capability awareness,
- vision and multimodal chat,
- image generation and editing,
- audio speech and transcription,
- video generation,
- embeddings-backed semantic project context,
- safe tool/function calling,
- batch jobs and long-running workflows.

## Current focus: core API + richer chat

The first upgrade track is foundation work that keeps existing commands backward-compatible while exposing more of the OpenAI-compatible chat API.

Planned/started items:

- Support preferred `POLLINATIONS_KEY` auth while preserving `POLLINATION_API_KEY` and `POLLIX_API_KEY` aliases.
- Keep `pollix models` for bundled model IDs and add live model discovery.
- Pass through richer chat controls such as `top_p`, penalties, seeds, and JSON response format.
- Keep the API client endpoint/payload shape aligned with Pollinations' OpenAI-compatible `/v1/chat/completions` API.

## Next phases

1. **API architecture cleanup**
   - Split chat, models, image, audio, video, embeddings, and realtime code into focused API modules.
   - Add typed request/response objects and test fixtures for payload compatibility.

2. **Vision and multimodal chat**
   - Add `--image` attachments for local files, public URLs, and data URIs.
   - Add image detail controls and model compatibility warnings.

3. **Image commands**
   - Add `pollix image generate` and `pollix image edit`.
   - Support model, dimensions, seed, private, enhance, and output file options.

4. **Audio commands**
   - Add `pollix audio speak` for text-to-speech.
   - Add `pollix audio transcribe` with JSON/text/SRT/VTT output formats.

5. **Embeddings and semantic context**
   - Add `pollix embed` and `pollix search`.
   - Add `--context-mode semantic` for retrieval-based codebase context.

6. **Safe tools and batch workflows**
   - Add explicit opt-in local tools for filesystem/git/shell workflows.
   - Add `pollix jobs` for long-running batch review, edit, media, and indexing tasks.
