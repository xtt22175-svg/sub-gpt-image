---
name: sub2api-image
description: Use when the user wants to configure Sub2API image credentials, generate images, edit local images, batch-generate images, or run image API health/model checks inside Codex.
---

# Sub2API Image

Use this plugin's MCP tools for Sub2API/OpenAI-compatible image generation and editing.

## Workflow

1. If the user provides a Sub2API base URL and API key, call `configure_sub2api` first. Do not echo the key.
2. After first-time configuration, call `health_check`. If it fails, summarize the redacted error and ask for corrected credentials or endpoint.
3. For one prompt, call `generate_image`.
4. For a local input image path plus an edit instruction, call `edit_image`.
5. For multiple prompts or requested 2K/4K simultaneous generation, call `generate_batch` with the requested concurrency.
6. In the final reply, report only image path(s), model, size, quality, format, elapsed time, and any redacted failures.

## Defaults

- Default model is the configured default model, usually `gpt-image-2`.
- Default size is `1024x1024` unless the user asks for another size.
- Use `2048x1152` for 2K 16:9 and `3840x2160` for 4K 16:9 when the user asks for 2K/4K.
- Default quality is `auto`.
- Default output format is `png`.
- If no output directory is requested, let the tool save under the plugin's private output directory.

## Security

- Never reveal API keys, authorization tokens, or raw private endpoint hosts in messages.
- If the user asks to share logs or errors, redact secrets before responding.
- The key is stored locally by `configure_sub2api` under Codex plugin private data.

## Tool Hints

- `configure_sub2api(base_url, api_key, default_model?)`
- `health_check()`
- `list_image_models()`
- `generate_image(prompt, size?, quality?, model?, output_format?, output_dir?)`
- `edit_image(image_path, prompt, mask_path?, size?, quality?, model?, output_format?, output_dir?)`
- `generate_batch(items[], concurrency?, output_dir?)`
