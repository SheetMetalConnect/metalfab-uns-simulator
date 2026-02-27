#!/bin/bash
# Setup script for MetalFab UNS MCP Server

set -e

echo "========================================="
echo "MetalFab UNS MCP Server Setup"
echo "========================================="
echo

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 not found"
    echo "Please install Python 3.11 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
echo "✓ Found Python $PYTHON_VERSION"

# Create virtual environment
echo
echo "Creating virtual environment..."
python3 -m venv venv

# Activate and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip > /dev/null
pip install -r requirements.txt

echo
echo "✓ Setup complete!"
echo
echo "========================================="
echo "Next Steps:"
echo "========================================="
echo
echo "1. Make sure MetalFab simulator is running:"
echo "   cd .."
echo "   metalfab-sim run --level 3"
echo
echo "2. Get the absolute path for Claude config:"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "   MCP Server path: $SCRIPT_DIR"
echo
echo "3. Add to Claude Desktop config:"
echo
echo '   {
     "mcpServers": {
       "metalfab-uns": {
         "command": "'$SCRIPT_DIR'/venv/bin/python",
         "args": ["'$SCRIPT_DIR'/src/metalfab_mcp_server.py"]
       }
     }
   }'
echo
echo "   Config file location:"
echo "   - macOS: ~/Library/Application Support/Claude/claude_desktop_config.json"
echo "   - Windows: %APPDATA%\\Claude\\claude_desktop_config.json"
echo
echo "4. Restart Claude Desktop"
echo
echo "========================================="
echo "Test the server:"
echo "========================================="
echo
echo "After restarting Claude Desktop, try:"
echo '  "What is the MetalFab UNS structure?"'
echo '  "Show me machines in Eindhoven"'
echo '  "What is the current simulator status?"'
echo
