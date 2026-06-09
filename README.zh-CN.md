# Sub2API Image for Codex 使用指南

Sub2API Image 是一个面向 Codex 的图片生成插件。它将用户自己的 Sub2API / OpenAI-compatible Images API 接入 Codex，让 Codex 可以根据自然语言完成图片生成、图片编辑和批量生成。

仓库不内置 API key，也不绑定任何私有服务地址。使用者需要配置自己的 Sub2API 地址和 key。

## 转发模板

以下内容可直接转发给使用者：

```text
请把这个仓库链接提供给 Codex，并让 Codex 安装插件：
https://github.com/xtt22175-svg/sub-gpt-image

安装后，把你自己的 Sub2API base_url、api_key 和图片提示词发给 Codex。
Codex 会完成配置、检查连接，并直接开始生成或编辑图片。
不要让 Codex 在回复中回显你的 API key。
```

## 安装与配置

在 Codex 中发送：

```text
请安装这个 Codex 插件：
https://github.com/xtt22175-svg/sub-gpt-image

安装完成后，使用以下信息配置 Sub2API Image：
- base_url: https://your-sub2api.example/v1
- api_key: <YOUR_SUB2API_API_KEY>
- default_model: gpt-image-2

配置后先检查连接。如果可用，再按我的提示词生成图片。
不要回显我的 API key。
```

配置完成后，key 会保存在本机 Codex 插件私有数据目录中。后续使用同一个 Codex 环境时，通常不需要重复配置。

## 基本使用

生成单张图片：

```text
用 Sub2API Image 生成一张 1024x1024 的图片。
提示词：一间清晨阳光里的现代书房，木质桌面，柔和自然光，真实摄影风格。
```

指定参数生成：

```text
用 Sub2API Image 生成图片：
- model: gpt-image-2
- size: 1536x1024
- quality: high
- output_format: png

提示词：...
```

编辑本地图片：

```text
用 Sub2API Image 编辑这张图片：
C:\path\to\image.png

编辑要求：保持主体不变，把背景替换为干净的产品摄影棚背景，光线自然。
```

同时生成 2K 和 4K：

```text
用 Sub2API Image 并发生成两张图，concurrency 设置为 2：
- 2K: 2048x1152
- 4K: 3840x2160

提示词：一张高端科技产品海报，深色背景，清晰主体，细节锐利，商业摄影风格。
返回每张图的保存路径、模型、尺寸、格式和耗时。
```

批量生成多张图片：

```text
用 Sub2API Image 批量生成 4 张图片，concurrency 设置为 2。
每张图分别使用下面的提示词：
1. ...
2. ...
3. ...
4. ...

结果保存到本地输出目录，并返回文件路径。
```

## 返回内容

生成或编辑完成后，Codex 会返回图片的本地保存路径，并附带模型、尺寸、格式和耗时等必要信息。

默认情况下，图片保存到插件私有输出目录。需要保存到指定位置时，可以在请求中说明输出目录。

## 安全边界

- 仓库不包含任何 API key 或私有 endpoint。
- 使用者的 key 只保存在本机 Codex 插件私有数据目录中。
- 插件会尽量在结果和错误信息中遮蔽 key、token 和 endpoint host。
- 不建议对外发送包含 key 的聊天记录、终端输出、日志或截图。

## 环境要求

- Codex 支持插件安装和 MCP 工具调用。
- 本机可使用 Python 3.10 或更高版本。
- Sub2API 服务兼容 OpenAI Images API。

如果目标机器的 Python 命令是 `python3`，请让 Codex 在安装前把 `.mcp.json` 中的 `"command": "python"` 改为 `"command": "python3"`。
