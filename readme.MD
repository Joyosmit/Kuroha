        ██╗  ██╗██╗   ██╗██████╗  ██████╗ ██╗  ██╗ █████╗
        ██║ ██╔╝██║   ██║██╔══██╗██╔═══██╗██║  ██║██╔══██╗
        █████╔╝ ██║   ██║██████╔╝██║   ██║███████║███████║
        ██╔═██╗ ██║   ██║██╔══██╗██║   ██║██╔══██║██╔══██║
        ██║  ██╗╚██████╔╝██║  ██║╚██████╔╝██║  ██║██║  ██║
        ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝

<div align="center">

# ⚡ Model Context Protocol (MCP) Agent Harness

**A lightweight, extensible Python agent runtime with dynamic Model Context Protocol integration and local tool execution.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![MCP SDK](https://img.shields.io/badge/MCP%20SDK-v2.0%2B-purple?style=flat-square)](https://github.com/modelcontextprotocol)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## 💡 Overview

This library provides an asynchronous agent execution loop designed to seamlessly blend **native Python functions** with **external MCP subprocess servers** (Model Context Protocol). Built to target OpenAI-compatible inference endpoints (such as Google AI Studio), it manages complex multi-turn reasoning, tool routing, schema translation, and graceful subprocess lifecycle management.

### Key Features

* **🔌 Dual Tool Architecture**: Register fast in-process Python functions or connect external stdio-based MCP tool servers natively.
* **🔁 Automatic Tool Discovery**: Dynamically fetches and namespaces tools from connected MCP servers at runtime.
* **⚡ Non-blocking Execution**: Uses `asyncio` for subprocess control and offloads synchronous network requests to worker threads via `asyncio.to_thread()`.
* **🛡️ Client-side Model Failovers**: Built-in retry mechanism across a prioritized list of fallback models.
* **🧹 Resource Safety**: Automated cleanup of MCP subprocess channels via `AsyncExitStack`.

---

## 📦 Installation

Ensure you have Python 3.10+ (I used Python 3.12.6) installed. Then create a virtual environment using

```bash
uv venv
```

Then activate the venv using

i. For Windows:
```bash
./venv/Scripts/activate
```

ii. For MacOS and Linux:
```bash
source ./venv/Scripts/activate
```

Install the packages
```bash
uv pip install -r requirements.txt
```