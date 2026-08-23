import asyncio
import os
import shlex
import subprocess
from pathlib import Path

# --- Updated Imports for mcp >= 2.0.0 ---
from mcp.server.mcpserver import MCPServer

# Initialize Server (FastMCP was renamed to MCPServer in 2.0+)
mcp = MCPServer("Python-Bash-MCP")

FORBIDDEN_COMMANDS = {
    "rm", "mkfs", "dd", "shutdown", "reboot", "chmod", "chown", "sudo", "su"
}

@mcp.tool()
async def pwd() -> str:
    """Returns the current absolute working directory path."""
    return os.getcwd()

@mcp.tool()
async def ls(path: str = ".") -> str:
    """Lists files and directories in the specified path."""
    try:
        target_path = Path(path).resolve()
        if not target_path.exists():
            return f"Error: Path '{path}' does not exist."
        
        items = os.listdir(target_path)
        formatted = []
        for item in sorted(items):
            item_path = target_path / item
            kind = "[DIR] " if item_path.is_dir() else "[FILE]"
            formatted.append(f"{kind} {item}")
            
        return "\n".join(formatted) if formatted else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {str(e)}"

@mcp.tool()
async def cat(filepath: str) -> str:
    """Reads and returns the contents of a text file."""
    try:
        target_file = Path(filepath).resolve()
        if not target_file.exists():
            return f"Error: File '{filepath}' does not exist."
        if target_file.is_dir():
            return f"Error: '{filepath}' is a directory, not a file."
            
        if target_file.stat().st_size > 1_000_000:
            return f"Error: File '{filepath}' exceeds max safe size (1MB)."

        return target_file.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
async def run_command(command: str) -> str:
    """Executes a safe shell command and returns stdout and stderr."""
    tokens = shlex.split(command)
    if not tokens:
        return "Error: Empty command."
        
    base_cmd = tokens[0].lower()
    if base_cmd in FORBIDDEN_COMMANDS:
        return f"Security Error: Command '{base_cmd}' is disallowed by policy."

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd()
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            return "Execution Error: Command timed out after 30 seconds."

        output = stdout.decode(errors="replace").strip()
        errors = stderr.decode(errors="replace").strip()

        result = []
        if output:
            result.append(f"STDOUT:\n{output}")
        if errors:
            result.append(f"STDERR:\n{errors}")

        return "\n".join(result) if result else "Command executed with no output."

    except Exception as e:
        return f"Execution failed: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")