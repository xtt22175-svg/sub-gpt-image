#!/usr/bin/env python3
"""Codex MCP server for Sub2API OpenAI-compatible image generation.

This server intentionally uses only the Python standard library so the plugin
can be installed from a Git repository without a separate dependency step.
"""

from __future__ import annotations

import base64
import concurrent.futures
import datetime as dt
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib import error, parse, request


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "sub2api-image"
SERVER_VERSION = "0.1.2"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "auto"
DEFAULT_OUTPUT_FORMAT = "png"
DEFAULT_TIMEOUT_SECONDS = 420.0
DEFAULT_RETRY_ATTEMPTS = 1
DEFAULT_RETRY_BASE_DELAY_SECONDS = 2.0
VALID_OUTPUT_FORMATS = {"png", "jpeg", "jpg", "webp"}
VALID_QUALITIES = {"low", "medium", "high", "auto"}
MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
MAX_EDGE = 3_840

_SIZE_RE = re.compile(r"^([1-9][0-9]*)x([1-9][0-9]*)$")
_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_OPENAI_KEY_RE = re.compile(r"\b(?:sk|sess|org|proj)-[A-Za-z0-9_-]{8,}\b")
_URL_RE = re.compile(r"\b(https?://)([^/\s\"']+)(/[^\s\"']*)?")


def plugin_data_dir() -> Path:
    value = os.environ.get("PLUGIN_DATA")
    if value:
        return Path(value)
    return Path.home() / ".codex" / "sub2api-image"


def config_path() -> Path:
    return plugin_data_dir() / "config.json"


def default_output_dir() -> Path:
    return plugin_data_dir() / "outputs"


def redact_text(text: str, extra_secrets: list[str] | None = None) -> str:
    redacted = str(text)
    for secret in extra_secrets or []:
        if secret:
            redacted = redacted.replace(secret, "<redacted-token>")
    redacted = _BEARER_RE.sub("Bearer <redacted-token>", redacted)
    redacted = _OPENAI_KEY_RE.sub("<redacted-token>", redacted)

    def replace_url(match: re.Match[str]) -> str:
        suffix = match.group(3) or ""
        return f"{match.group(1)}<redacted-host>{suffix}"

    return _URL_RE.sub(replace_url, redacted)


def normalize_base_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("base_url is required.")
    parsed = parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http(s) URL.")
    return raw.rstrip("/")


def normalize_output_format(value: Any) -> str:
    fmt = str(value or DEFAULT_OUTPUT_FORMAT).strip().lower()
    if fmt not in VALID_OUTPUT_FORMATS:
        raise ValueError("output_format must be one of png, jpeg, jpg, or webp.")
    if fmt == "jpg":
        return "jpeg"
    return fmt


def file_extension_for_format(output_format: str) -> str:
    return "jpg" if output_format == "jpeg" else output_format


def validate_quality(value: Any) -> str:
    quality = str(value or DEFAULT_QUALITY).strip().lower()
    if quality not in VALID_QUALITIES:
        raise ValueError("quality must be one of low, medium, high, or auto.")
    return quality


def validate_size(value: Any) -> str:
    size = str(value or DEFAULT_SIZE).strip().lower()
    if size == "auto":
        return size
    match = _SIZE_RE.match(size)
    if not match:
        raise ValueError("size must be WIDTHxHEIGHT, for example 1024x1024, or auto.")

    width = int(match.group(1))
    height = int(match.group(2))
    if width % 16 != 0 or height % 16 != 0:
        raise ValueError("size width and height must be multiples of 16.")
    ratio = width / height
    if ratio > 3 or ratio < (1 / 3):
        raise ValueError("size aspect ratio must be between 1:3 and 3:1.")
    pixels = width * height
    if pixels < MIN_PIXELS or pixels > MAX_PIXELS:
        raise ValueError(
            f"size total pixels must be between {MIN_PIXELS} and {MAX_PIXELS}."
        )
    if max(width, height) > MAX_EDGE:
        raise ValueError(f"size max edge must be <= {MAX_EDGE}px.")
    return size


def safe_label(value: str) -> str:
    cleaned = _SAFE_LABEL_RE.sub("-", value.strip())[:80].strip("-")
    return cleaned or "image"


def markdown_alt_text(value: str) -> str:
    cleaned = re.sub(r"[\[\]\r\n]+", " ", str(value)).strip()
    return cleaned or "image"


def markdown_image_path(path: Path) -> str:
    return path.resolve().as_posix()


def unique_output_path(output_dir: Path, label: str, output_format: str, timestamp: float) -> Path:
    stamp = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    ext = file_extension_for_format(output_format)
    stem = f"{stamp}-{safe_label(label)}"
    candidate = output_dir / f"{stem}.{ext}"
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = output_dir / f"{stem}-{index}.{ext}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not allocate a unique output filename.")


def resolve_output_dir(value: Any) -> Path:
    if value:
        return Path(str(value)).expanduser().resolve()
    return default_output_dir().resolve()


def write_private_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temp_path, 0o600)
    except OSError:
        pass
    temp_path.replace(path)


def read_private_config() -> dict[str, Any] | None:
    path = config_path()
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Sub2API config is invalid. Run configure_sub2api again.")
    return payload


def require_config() -> dict[str, str]:
    config = read_private_config()
    if not config:
        raise RuntimeError(
            "Sub2API is not configured. Call configure_sub2api with base_url and api_key first."
        )
    base_url = normalize_base_url(str(config.get("base_url") or ""))
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("Sub2API api_key is missing. Call configure_sub2api again.")
    default_model = str(config.get("default_model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return {"base_url": base_url, "api_key": api_key, "default_model": default_model}


def endpoint_url(config: dict[str, str], path: str) -> str:
    return f"{config['base_url'].rstrip('/')}/{path.lstrip('/')}"


def normalize_retry_attempts(value: Any) -> int:
    attempts = int(value if value is not None else DEFAULT_RETRY_ATTEMPTS)
    if attempts < 0 or attempts > 5:
        raise ValueError("retry_attempts must be between 0 and 5.")
    return attempts


def retry_delay_seconds(attempt_index: int, value: Any = None) -> float:
    base_delay = float(value if value is not None else DEFAULT_RETRY_BASE_DELAY_SECONDS)
    if base_delay < 0 or base_delay > 30:
        raise ValueError("retry_base_delay_seconds must be between 0 and 30.")
    return base_delay * (2 ** max(0, attempt_index - 1))


def is_retryable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    retryable_fragments = (
        "remote end closed connection without response",
        "unexpected_eof_while_reading",
        "eof occurred in violation of protocol",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "http 408",
        "http 409",
        "http 425",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "http 520",
        "http 522",
        "http 524",
    )
    return any(fragment in text for fragment in retryable_fragments)


def call_with_retries(operation: Any, args: dict[str, Any]) -> tuple[dict[str, Any], int]:
    retry_attempts = normalize_retry_attempts(args.get("retry_attempts"))
    last_error: Exception | None = None
    for attempt_index in range(retry_attempts + 1):
        try:
            return operation(), attempt_index + 1
        except Exception as exc:  # noqa: BLE001 - retries preserve final redacted error.
            last_error = exc
            if attempt_index >= retry_attempts or not is_retryable_error(exc):
                raise
            time.sleep(retry_delay_seconds(attempt_index + 1, args.get("retry_base_delay_seconds")))
    raise RuntimeError(str(last_error or "Image request failed."))


def response_to_json(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Image API returned non-JSON data: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Image API returned JSON that is not an object.")
    return payload


def request_json(
    *,
    config: dict[str, str],
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = endpoint_url(config, path)
    body = None
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return response_to_json(resp.read())
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        message = f"HTTP {exc.code} from {url}: {detail}"
        raise RuntimeError(redact_text(message, [config["api_key"]])) from exc
    except error.URLError as exc:
        message = f"Network error from {url}: {exc}"
        raise RuntimeError(redact_text(message, [config["api_key"]])) from exc


def build_multipart_body(
    *,
    fields: dict[str, Any],
    files: list[tuple[str, Path]],
) -> tuple[bytes, str]:
    boundary = f"----codex-sub2api-image-{int(time.time() * 1000)}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        if value in (None, ""):
            continue
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for field_name, path in files:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8")
        )
        chunks.append(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def request_multipart(
    *,
    config: dict[str, str],
    path: str,
    fields: dict[str, Any],
    files: list[tuple[str, Path]],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = endpoint_url(config, path)
    body, boundary = build_multipart_body(fields=fields, files=files)
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return response_to_json(resp.read())
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        message = f"HTTP {exc.code} from {url}: {detail}"
        raise RuntimeError(redact_text(message, [config["api_key"]])) from exc
    except error.URLError as exc:
        message = f"Network error from {url}: {exc}"
        raise RuntimeError(redact_text(message, [config["api_key"]])) from exc


def download_bytes(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except error.URLError as exc:
        raise RuntimeError(redact_text(f"Could not download generated image from {url}: {exc}")) from exc


def decode_image_item(item: dict[str, Any]) -> bytes:
    if isinstance(item.get("b64_json"), str):
        encoded = item["b64_json"]
        if encoded.lstrip().lower().startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        return base64.b64decode(encoded, validate=True)
    if isinstance(item.get("url"), str):
        return download_bytes(item["url"])
    raise RuntimeError("Image API response did not include b64_json or url.")


def save_image_response(
    *,
    response: dict[str, Any],
    output_dir: Path,
    label: str,
    output_format: str,
    started_at: float,
    ended_at: float,
) -> dict[str, Any]:
    data_items = response.get("data")
    if not isinstance(data_items, list) or not data_items:
        raise RuntimeError("Image API response did not include data[0].")
    first = data_items[0]
    if not isinstance(first, dict):
        raise RuntimeError("Image API response data[0] was not an object.")

    image_bytes = decode_image_item(first)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = unique_output_path(output_dir, label, output_format, started_at)
    output_path.write_bytes(image_bytes)

    result: dict[str, Any] = {
        "path": str(output_path.resolve()),
        "preview_markdown": f"![{markdown_alt_text(label)}]({markdown_image_path(output_path)})",
        "bytes": len(image_bytes),
        "elapsed_seconds": round(ended_at - started_at, 3),
    }
    revised_prompt = first.get("revised_prompt")
    if isinstance(revised_prompt, str) and revised_prompt:
        result["revised_prompt"] = revised_prompt
    return result


def build_image_payload(args: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required.")
    model = str(args.get("model") or config["default_model"]).strip() or config["default_model"]
    output_format = normalize_output_format(args.get("output_format"))
    payload = {
        "model": model,
        "prompt": prompt,
        "size": validate_size(args.get("size")),
        "quality": validate_quality(args.get("quality")),
        "n": 1,
        "output_format": output_format,
    }
    return payload


def call_configure_sub2api(args: dict[str, Any]) -> dict[str, Any]:
    base_url = normalize_base_url(str(args.get("base_url") or ""))
    api_key = str(args.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("api_key is required.")
    default_model = str(args.get("default_model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    write_private_config(
        {
            "base_url": base_url,
            "api_key": api_key,
            "default_model": default_model,
            "configured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )
    return {
        "configured": True,
        "base_url": redact_text(base_url),
        "default_model": default_model,
        "message": "Sub2API image configuration saved in this plugin's private data directory.",
    }


def call_list_image_models(args: dict[str, Any] | None = None) -> dict[str, Any]:
    config = require_config()
    started_at = time.time()
    response = request_json(config=config, method="GET", path="/models", timeout=60.0)
    model_ids: list[str] = []
    for item in response.get("data", []):
        model_id = item.get("id") if isinstance(item, dict) else None
        if isinstance(model_id, str):
            lowered = model_id.lower()
            if "image" in lowered or "dall" in lowered or "imagen" in lowered:
                model_ids.append(model_id)
    return {
        "models": sorted(set(model_ids)),
        "default_model": config["default_model"],
        "elapsed_seconds": round(time.time() - started_at, 3),
    }


def call_health_check(args: dict[str, Any] | None = None) -> dict[str, Any]:
    config = require_config()
    started_at = time.time()
    result: dict[str, Any] = {
        "ok": True,
        "configured": True,
        "base_url": redact_text(config["base_url"]),
        "default_model": config["default_model"],
        "generation_endpoint": "/images/generations",
        "edit_endpoint": "/images/edits",
    }
    try:
        models = call_list_image_models({}).get("models", [])
        result["models_ok"] = True
        result["image_models"] = models
    except Exception as exc:  # noqa: BLE001 - health check reports redacted diagnostics.
        result["models_ok"] = False
        result["models_error"] = redact_text(str(exc), [config["api_key"]])
    result["elapsed_seconds"] = round(time.time() - started_at, 3)
    return result


def call_generate_image(args: dict[str, Any]) -> dict[str, Any]:
    config = require_config()
    payload = build_image_payload(args, config)
    output_format = str(payload["output_format"])
    output_dir = resolve_output_dir(args.get("output_dir"))
    label = str(args.get("label") or payload["size"] or "image")
    started_at = time.time()
    response, attempts = call_with_retries(
        lambda: request_json(
            config=config,
            method="POST",
            path="/images/generations",
            payload=payload,
            timeout=float(args.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        ),
        args,
    )
    ended_at = time.time()
    saved = save_image_response(
        response=response,
        output_dir=output_dir,
        label=label,
        output_format=output_format,
        started_at=started_at,
        ended_at=ended_at,
    )
    saved.update(
        {
            "model": payload["model"],
            "size": payload["size"],
            "quality": payload["quality"],
            "output_format": output_format,
            "attempts": attempts,
        }
    )
    return saved


def call_edit_image(args: dict[str, Any]) -> dict[str, Any]:
    config = require_config()
    image_path = Path(str(args.get("image_path") or "")).expanduser().resolve()
    if not image_path.is_file():
        raise ValueError(f"image_path does not exist or is not a file: {image_path}")

    mask_arg = args.get("mask_path")
    files = [("image", image_path)]
    if mask_arg:
        mask_path = Path(str(mask_arg)).expanduser().resolve()
        if not mask_path.is_file():
            raise ValueError(f"mask_path does not exist or is not a file: {mask_path}")
        files.append(("mask", mask_path))

    payload = build_image_payload(args, config)
    fields = {key: value for key, value in payload.items() if key != "n"}
    output_format = str(payload["output_format"])
    output_dir = resolve_output_dir(args.get("output_dir"))
    label = str(args.get("label") or f"edit-{image_path.stem}")
    started_at = time.time()
    response, attempts = call_with_retries(
        lambda: request_multipart(
            config=config,
            path="/images/edits",
            fields=fields,
            files=files,
            timeout=float(args.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        ),
        args,
    )
    ended_at = time.time()
    saved = save_image_response(
        response=response,
        output_dir=output_dir,
        label=label,
        output_format=output_format,
        started_at=started_at,
        ended_at=ended_at,
    )
    saved.update(
        {
            "model": payload["model"],
            "size": payload["size"],
            "quality": payload["quality"],
            "output_format": output_format,
            "source_image_path": str(image_path),
            "attempts": attempts,
        }
    )
    return saved


def call_generate_batch(args: dict[str, Any]) -> dict[str, Any]:
    items = args.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty array.")
    concurrency = int(args.get("concurrency") or min(4, len(items)))
    if concurrency < 1 or concurrency > 8:
        raise ValueError("concurrency must be between 1 and 8.")
    output_dir = args.get("output_dir")
    total_started = time.time()

    def build_item(raw_item: Any, index: int) -> dict[str, Any]:
        if not isinstance(raw_item, dict):
            raise ValueError(f"items[{index}] must be an object.")
        merged = {
            "model": args.get("model"),
            "size": args.get("size"),
            "quality": args.get("quality"),
            "output_format": args.get("output_format"),
            "retry_attempts": args.get("retry_attempts"),
            "retry_base_delay_seconds": args.get("retry_base_delay_seconds"),
            "output_dir": output_dir,
            **raw_item,
        }
        if not merged.get("label"):
            merged["label"] = str(merged.get("size") or f"item-{index + 1}")
        return merged

    jobs = [build_item(item, index) for index, item in enumerate(items)]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_index = {
            executor.submit(call_generate_image, job): index for index, job in enumerate(jobs)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                result["index"] = index
                results.append(result)
            except Exception as exc:  # noqa: BLE001 - batch reports per-item failures.
                failures.append(
                    {
                        "index": index,
                        "label": jobs[index].get("label"),
                        "error": redact_text(str(exc)),
                    }
                )

    results.sort(key=lambda item: item["index"])
    failures.sort(key=lambda item: item["index"])
    return {
        "results": results,
        "failures": failures,
        "concurrency": concurrency,
        "total_elapsed_seconds": round(time.time() - total_started, 3),
    }


def tools_list() -> list[dict[str, Any]]:
    return [
        {
            "name": "configure_sub2api",
            "description": (
                "Save the user's Sub2API base URL and API key into this plugin's "
                "private PLUGIN_DATA config. Never echo the key back to the user."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "base_url": {
                        "type": "string",
                        "description": "OpenAI-compatible API base URL, usually ending in /v1.",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "User's private Sub2API API key.",
                    },
                    "default_model": {
                        "type": "string",
                        "description": "Default image model.",
                        "default": DEFAULT_MODEL,
                    },
                },
                "required": ["base_url", "api_key"],
            },
        },
        {
            "name": "health_check",
            "description": "Check whether the configured Sub2API endpoint is reachable.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_image_models",
            "description": "List image-looking models from the configured Sub2API /models endpoint.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "generate_image",
            "description": "Generate one image, save it locally, and return the absolute file path.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Image generation prompt."},
                    "size": {
                        "type": "string",
                        "description": "Image size such as 1024x1024, 2048x1152, 3840x2160, or auto.",
                        "default": DEFAULT_SIZE,
                    },
                    "quality": {
                        "type": "string",
                        "description": "low, medium, high, or auto.",
                        "default": DEFAULT_QUALITY,
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional image model override.",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "png, jpeg, or webp.",
                        "default": DEFAULT_OUTPUT_FORMAT,
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional local output directory.",
                    },
                    "retry_attempts": {
                        "type": "integer",
                        "description": "Retry count for transient gateway or connection failures, 0 to 5.",
                        "minimum": 0,
                        "maximum": 5,
                        "default": DEFAULT_RETRY_ATTEMPTS,
                    },
                },
                "required": ["prompt"],
            },
        },
        {
            "name": "edit_image",
            "description": "Edit one local image path with a prompt, optional mask, and save the result.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "Local image file path."},
                    "prompt": {"type": "string", "description": "Image edit prompt."},
                    "mask_path": {"type": "string", "description": "Optional local mask image path."},
                    "size": {
                        "type": "string",
                        "description": "Image size such as 1024x1024, 2048x1152, 3840x2160, or auto.",
                        "default": DEFAULT_SIZE,
                    },
                    "quality": {
                        "type": "string",
                        "description": "low, medium, high, or auto.",
                        "default": DEFAULT_QUALITY,
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional image model override.",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "png, jpeg, or webp.",
                        "default": DEFAULT_OUTPUT_FORMAT,
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional local output directory.",
                    },
                    "retry_attempts": {
                        "type": "integer",
                        "description": "Retry count for transient gateway or connection failures, 0 to 5.",
                        "minimum": 0,
                        "maximum": 5,
                        "default": DEFAULT_RETRY_ATTEMPTS,
                    },
                },
                "required": ["image_path", "prompt"],
            },
        },
        {
            "name": "generate_batch",
            "description": "Generate multiple images concurrently and return per-item file paths.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Generation items. Each item should include prompt and may override size, model, quality, output_format, or label.",
                        "items": {"type": "object"},
                    },
                    "concurrency": {
                        "type": "integer",
                        "description": "Parallel job count, 1 to 8.",
                        "minimum": 1,
                        "maximum": 8,
                        "default": 2,
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional local output directory used by all items unless overridden.",
                    },
                    "model": {"type": "string", "description": "Optional batch default model."},
                    "quality": {
                        "type": "string",
                        "description": "Optional batch default quality.",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Optional batch default output format.",
                    },
                    "retry_attempts": {
                        "type": "integer",
                        "description": "Retry count for transient gateway or connection failures, 0 to 5.",
                        "minimum": 0,
                        "maximum": 5,
                        "default": DEFAULT_RETRY_ATTEMPTS,
                    },
                },
                "required": ["items"],
            },
        },
    ]


def tool_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False, indent=2),
            }
        ]
    }


def tool_error(message: str) -> dict[str, Any]:
    try:
        config = read_private_config() or {}
    except Exception:  # noqa: BLE001 - error formatting must never fail.
        config = {}
    secret = str(config.get("api_key") or "")
    return {
        "isError": True,
        "content": [{"type": "text", "text": redact_text(message, [secret])}],
    }


def handle_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "configure_sub2api":
        return tool_result(call_configure_sub2api(args))
    if name == "health_check":
        return tool_result(call_health_check(args))
    if name == "list_image_models":
        return tool_result(call_list_image_models(args))
    if name == "generate_image":
        return tool_result(call_generate_image(args))
    if name == "edit_image":
        return tool_result(call_edit_image(args))
    if name == "generate_batch":
        return tool_result(call_generate_batch(args))
    return tool_error(f"Unknown tool: {name}")


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            result = {"tools": tools_list()}
        elif method == "tools/call":
            params = message.get("params") or {}
            if not isinstance(params, dict):
                result = tool_error("tools/call params must be an object.")
            else:
                name = str(params.get("name") or "")
                args = params.get("arguments") or {}
                if not isinstance(args, dict):
                    result = tool_error("tools/call arguments must be an object.")
                else:
                    result = handle_tool_call(name, args)
        else:
            result = tool_error(f"Unknown method: {method}")
    except Exception as exc:  # noqa: BLE001 - convert tool exceptions to MCP tool errors.
        result = tool_error(str(exc))
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def parse_line_or_header(first_line: bytes, stream: Any) -> dict[str, Any] | None:
    stripped = first_line.strip()
    if not stripped:
        return None
    if stripped.lower().startswith(b"content-length:"):
        try:
            length = int(stripped.split(b":", 1)[1].strip())
        except ValueError as exc:
            raise RuntimeError("Invalid Content-Length header.") from exc
        while True:
            header = stream.readline()
            if header in (b"\r\n", b"\n", b""):
                break
        payload = stream.read(length)
        return json.loads(payload.decode("utf-8-sig"))
    return json.loads(stripped.decode("utf-8-sig"))


def read_messages() -> Any:
    stream = sys.stdin.buffer
    while True:
        first_line = stream.readline()
        if first_line == b"":
            break
        message = parse_line_or_header(first_line, stream)
        if message is not None:
            yield message


def write_message(message: dict[str, Any]) -> None:
    data = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if os.environ.get("SUB2API_IMAGE_MCP_LINE_MODE") == "1":
        sys.stdout.write(data.decode("utf-8") + "\n")
        sys.stdout.flush()
        return
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main() -> None:
    for message in read_messages():
        response = handle_request(message)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--tools":
        print(json.dumps({"tools": tools_list()}, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    main()
