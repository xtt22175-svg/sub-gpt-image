# Sub2API Image for Codex

Codex plugin for image generation and editing through a user-configured Sub2API OpenAI-compatible Images API.

The repository contains only runtime code and user documentation. It does not include private endpoints, API keys, test assets, test logs, or private validation scripts.

## What To Send Someone

Send them this:

```text
Give this repository link to Codex, ask Codex to install the plugin, then provide your own Sub2API base URL, API key, and image prompt. Codex should configure Sub2API, run a health check, and generate or edit images directly from Codex.
```

## What The Recipient Can Paste Into Codex

Replace the placeholders with their own values:

```text
Install this Codex plugin from https://github.com/xtt22175-svg/sub-gpt-image.

After installing it, configure Sub2API image generation with:
- base_url: https://your-sub2api.example/v1
- api_key: <YOUR_SUB2API_API_KEY>
- default_model: gpt-image-2

Run health_check. If it passes, generate this image:
<YOUR_IMAGE_PROMPT>

Do not echo my API key in your response.
```

For simultaneous 2K and 4K generation:

```text
Use the Sub2API image plugin to generate two images at the same time:
- 2K: 2048x1152
- 4K: 3840x2160
- concurrency: 2
- prompt: <YOUR_IMAGE_PROMPT>

Return the saved file paths, model, size, quality, format, and elapsed time. Do not echo my API key.
```

## Codex Tools

The plugin exposes these MCP tools:

- `configure_sub2api(base_url, api_key, default_model?)`
- `health_check()`
- `list_image_models()`
- `generate_image(prompt, size?, quality?, model?, output_format?, output_dir?)`
- `edit_image(image_path, prompt, mask_path?, size?, quality?, model?, output_format?, output_dir?)`
- `generate_batch(items[], concurrency?, output_dir?)`

## Security Model

- No API key or private endpoint is committed to this repository.
- `configure_sub2api` stores the recipient's key on their own machine under Codex plugin private data (`PLUGIN_DATA/config.json`).
- Tool results and errors redact authorization tokens, `sk-*` style tokens, and endpoint hosts.
- Generated images are saved locally. By default, they are saved under the plugin's private data output folder unless `output_dir` is provided.

## Runtime Requirements

- Codex with plugin support.
- Python 3.10 or newer available as `python`.
- A Sub2API endpoint compatible with the OpenAI Images API:
  - `GET /models`
  - `POST /images/generations`
  - `POST /images/edits`

The server uses only the Python standard library. No `pip install` step is required.

If a recipient's machine only exposes Python as `python3`, update `.mcp.json` and change `"command": "python"` to `"command": "python3"` before installing.

## Local Development Notes

Public files are:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `server/sub2api_image_mcp.py`
- `skills/sub2api-image/SKILL.md`
- `README.md`
- `LICENSE`

Private smoke tests and live API validation should stay outside this repository before release.
