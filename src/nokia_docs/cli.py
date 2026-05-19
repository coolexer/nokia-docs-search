"""Click CLI entrypoint: nokia-docs <command>"""
import click
from nokia_docs.index import index_cmd


@click.group()
def main():
    """Nokia documentation search tools."""
    pass


main.add_command(index_cmd, name="index")


@main.command("serve")
def serve_cmd():
    """Start the MCP server (reads NOKIA_DOCS_DB env var)."""
    from nokia_docs.server import mcp
    mcp.run()
