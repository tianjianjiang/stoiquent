"""Minimal MCP server for integration testing.

Exposes two tools: 'echo' (returns its input) and 'add' (adds two numbers).
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Echo Test Server")


@mcp.tool()
def echo(message: str) -> str:
    """Echo back the given message."""
    return f"Echo: {message}"


@mcp.tool()
def add(a: int, b: int) -> str:
    """Add two numbers and return the result."""
    return str(a + b)


if __name__ == "__main__":
    mcp.run(transport="stdio")
