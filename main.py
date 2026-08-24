import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()


class AgentHarness:

    def __init__(
        self,
        primary_model: str = "gemma-4-31b-it",
        fallback_models: Optional[List[str]] = None,
        max_turns: int = 10,
        system_prompt: str = (
            "You are a helpful AI agent with access to local functions and MCP tools."
        ),
    ):
        # Fetch Google AI Studio API key
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required.")

        # Google AI Studio official OpenAI-compatible endpoint
        self.url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        self.primary_model = primary_model
        self.fallback_models = fallback_models or [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
        ]
        self.max_turns = max_turns

        # State & Registries
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        self.tools_schema: List[Dict[str, Any]] = []
        self.local_tool_handlers: Dict[str, Callable] = {}
        
        # Maps prefixed tool name -> (ClientSession, original_mcp_tool_name)
        self.mcp_sessions: Dict[str, Tuple[ClientSession, str]] = {}

        # Context manager stack to keep active MCP server pipes alive
        self._exit_stack = AsyncExitStack()

    # --- Local Tool Registration ---

    def register_local_tool(
        self, name: str, description: str, parameters: dict, handler: Callable
    ):
        """Registers a standard local Python function as a tool usable by the agent."""
        self.tools_schema.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        })
        self.local_tool_handlers[name] = handler

    # --- MCP Server Connection ---

    async def connect_mcp_stdio_server(
        self,
        server_name: str,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
    ):
        """Spawns an external MCP server via stdio and dynamically registers its tools."""
        server_params = StdioServerParameters(
            command=command, args=args, env=env
        )

        # Establish stdio transport streams and initialize MCP session
        stdio_transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = stdio_transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # Discover tools exposed by the MCP server
        mcp_tools_response = await session.list_tools()

        # Format each MCP tool into OpenAI-compatible schema specs
        for tool in mcp_tools_response.tools:
            # Prefix tool name with server name to prevent naming collisions
            tool_name = f"{server_name}_{tool.name}"

            self.tools_schema.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            })
            # Route execution to this specific session
            self.mcp_sessions[tool_name] = (session, tool.name)

        print(
            f"[MCP] Connected to '{server_name}'. Discovered {len(mcp_tools_response.tools)} tools."
        )

    # --- Synchronous API call execution worker ---

    def _sync_post(self, payload: dict, headers: dict) -> requests.Response:
        """Helper method to handle the blocking HTTP network call."""
        return requests.post(self.url, headers=headers, json=payload, timeout=60.0)

    # --- API Communication ---

    async def _call_gemini_api(self) -> dict:
        """Sends payload to Google AI Studio offloaded to a thread pool."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        models_to_try = [self.primary_model] + self.fallback_models
        last_exception = None

        for model in models_to_try:
            payload = {
                "model": model,
                "messages": self.messages,
            }
            if self.tools_schema:
                payload["tools"] = self.tools_schema

            try:
                # Offload blocking request call to a background worker thread
                response = await asyncio.to_thread(self._sync_post, payload, headers)

                if response.status_code == 200:
                    return response.json()

                print(
                    f"[Gemini API Error {response.status_code}] Model '{model}'"
                    f" failed: {response.text}. Trying fallback..."
                )
            except requests.RequestException as e:
                print(f"[Gemini Request Exception]: Model '{model}' failed with error: {e}")
                last_exception = e

        raise RuntimeError(
            f"All attempted Gemini models failed. Last error: {last_exception}"
        )

    # --- Tool Dispatcher ---

    async def _execute_tool_call(self, fn_name: str, raw_args: str) -> str:
        """Executes a tool call locally or dispatches it over RPC to an MCP server."""
        try:
            args = json.loads(raw_args) if raw_args else {}
        except Exception as e:
            return f"Error parsing arguments JSON: {str(e)}"

        # 1. Execute Local Python Function
        if fn_name in self.local_tool_handlers:
            try:
                result = self.local_tool_handlers[fn_name](**args)
                return (
                    json.dumps(result)
                    if not isinstance(result, str)
                    else result
                )
            except Exception as e:
                return f"Error executing local tool '{fn_name}': {str(e)}"

        # 2. Execute over Remote/External MCP Subprocess
        elif fn_name in self.mcp_sessions:
            session, mcp_tool_name = self.mcp_sessions[fn_name]
            try:
                mcp_result = await session.call_tool(
                    name=mcp_tool_name, arguments=args
                )

                # Consolidate textual content from CallToolResult
                content_items = []
                for content in mcp_result.content:
                    if content.type == "text":
                        content_items.append(content.text)
                    else:
                        content_items.append(f"[{content.type} content]")

                return "\n".join(content_items)
            except Exception as e:
                return f"MCP execution error for tool '{fn_name}': {str(e)}"

        else:
            return f"Tool '{fn_name}' not registered in harness."

    # --- Autonomous Loop ---

    async def run(self, user_prompt: str) -> str:
        """Executes autonomous reasoning loop: Prompt -> Reason -> Tool -> Result -> Reply."""
        self.messages.append({"role": "user", "content": user_prompt})

        for turn in range(self.max_turns):
            response_data = await self._call_gemini_api()
            choice = response_data["choices"][0]["message"]

            assistant_msg = {
                "role": choice.get("role", "assistant"),
                "content": choice.get("content"),
            }

            if choice.get("tool_calls"):
                assistant_msg["tool_calls"] = choice["tool_calls"]

            # 1. Update State with Model Response
            self.messages.append(assistant_msg)

            # 2. Check Termination: If model produced no tool calls, task is complete
            tool_calls = choice.get("tool_calls")
            if not tool_calls:
                return choice.get("content", "")

            # 3. Execution Phase
            for tool_call in tool_calls:
                fn_name = tool_call["function"]["name"]
                tool_call_id = tool_call["id"]
                raw_args = tool_call["function"]["arguments"]

                output_str = await self._execute_tool_call(
                    fn_name, raw_args
                )

                # 4. Feed Tool Output Back into Message State
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": output_str,
                })

        raise RuntimeError(
            f"Harness budget limit exceeded: Hit max limit of {self.max_turns} turns."
        )

    async def close(self):
        """Gracefully closes all underlying MCP server subprocesses."""
        await self._exit_stack.aclose()


# --- Example Integration Test ---


def calculate_expression(expression: str) -> str:
    """Safe inline mathematical expression evaluator."""
    try:
        return str(eval(expression, {"__builtins__": None}, {}))
    except Exception as e:
        return f"Calculation error: {e}"


async def main():
    harness = AgentHarness(
        primary_model="gemma-4-31b-it",
        fallback_models=["gemini-2.5-flash-lite", "gemini-2.5-flash"],
        max_turns=5,
    )

    try:
        # 1. Register a Local Native Python Tool
        calc_schema = {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression, e.g., '125 * 84'",
                }
            },
            "required": ["expression"],
        }
        harness.register_local_tool(
            name="calculator",
            description="Evaluates mathematical expressions.",
            parameters=calc_schema,
            handler=calculate_expression,
        )

        # 2. Connect a Local MCP Server Process (e.g., your bash_server.py)
        if os.path.exists("mcp_servers/bash_server.py"):
            print("Found mcp server")
            await harness.connect_mcp_stdio_server(
                server_name="bash",
                command=sys.executable,
                args=["mcp_servers/bash_server.py"],
            )

        prompt = "What is 12 plus 6, divided by 3?"
        print(f"\nUser: {prompt}")
        output = await harness.run(prompt)
        print("\nFinal Agent Response:\n", output)

        print("-"*10 + "NEXT PROMPT" + "-"*10)
        
        prompt = "Now print out 'goodbye' that many times in the terminal. And also print out the contents of requirements.txt to see if the versions are ok"
        print(f"\nUser: {prompt}")
        output = await harness.run(prompt)
        print("\nFinal Agent Response:\n", output)

    finally:
        # Ensures clean process shutdown for all MCP subprocess pipes
        await harness.close()


if __name__ == "__main__":
    asyncio.run(main())