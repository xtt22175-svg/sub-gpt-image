# Sub2API Image for Codex

Sub2API Image is a Codex plugin for connecting a user-owned Sub2API / OpenAI-compatible Images API to Codex. After configuration, Codex can generate images, edit local images, and run concurrent batch image jobs through natural language requests.

中文说明: [README.zh-CN.md](README.zh-CN.md)

This repository contains the plugin runtime and user-facing documentation only. It does not include any built-in API key or private endpoint.

## Install

Give this repository URL to Codex:

```text
https://github.com/xtt22175-svg/sub-gpt-image
```

A recipient can paste:

```text
Install this Codex plugin: https://github.com/xtt22175-svg/sub-gpt-image

After installation, configure it with my Sub2API base_url and api_key.
Run health_check first. If it passes, generate images from my prompt.
Do not echo my API key in your response.
```

## First-Time Configuration

Provide Codex with:

- `base_url`: Sub2API endpoint, for example `https://your-sub2api.example/v1`
- `api_key`: the user's own Sub2API API key
- `default_model`: optional default image model, for example `gpt-image-2`

Example:

```text
Configure Sub2API Image:
- base_url: https://your-sub2api.example/v1
- api_key: <YOUR_SUB2API_API_KEY>
- default_model: gpt-image-2

Then run health_check.
```

The key is stored on the user's machine in Codex plugin private data. It is not stored in this repository.

## Usage Examples

Generate one image:

```text
Use Sub2API Image to generate a 1024x1024 image.
Prompt: a modern reading room in soft morning light, realistic photography style.
```

Generate 2K and 4K concurrently:

```text
Use Sub2API Image to generate two images concurrently with concurrency set to 2:
- 2K: 2048x1152
- 4K: 3840x2160

Prompt: ...
Return the saved file paths, model, size, format, and elapsed time.
```

Edit a local image:

```text
Use Sub2API Image to edit this local image: C:\path\to\image.png
Edit request: keep the subject unchanged and replace the background with a clean studio backdrop.
```

## Tools

The plugin exposes these MCP tools to Codex:

- `configure_sub2api(base_url, api_key, default_model?)`
- `health_check()`
- `list_image_models()`
- `generate_image(prompt, size?, quality?, model?, output_format?, output_dir?)`
- `edit_image(image_path, prompt, mask_path?, size?, quality?, model?, output_format?, output_dir?)`
- `generate_batch(items[], concurrency?, output_dir?)`

In normal use, users do not need to call tool names manually. They can describe the image task directly in Codex.

## Output

Codex returns the generated file path, model, size, quality, format, and elapsed time. Images are saved locally, under the plugin private output directory by default unless `output_dir` is provided.

## Security

- No private API key or endpoint is committed to this repository.
- The user's API key is stored locally in Codex plugin private data.
- Tool results and errors redact tokens, keys, and endpoint hosts where possible.
- Do not share chat logs, screenshots, or terminal output that contain API keys.

## Requirements

- Codex with plugin and MCP tool support.
- Python 3.10 or newer available as `python`.
- A Sub2API service compatible with the OpenAI Images API:
  - `GET /models`
  - `POST /images/generations`
  - `POST /images/edits`

If the target machine exposes Python as `python3`, ask Codex to change `"command": "python"` to `"command": "python3"` in `.mcp.json` before installation.
