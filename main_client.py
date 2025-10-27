#!/usr/bin/env python3
"""
LAN Collaboration Client - Main Entry Point

Unified client with GUI interface that integrates:
- Chat messaging
- File transfer
- Screen sharing
- Audio streaming
- Video streaming

Usage:
    python main_client.py [--username NAME] [--gui | --cli]

Modes:
    --gui        Launch with PyQt6 GUI (default)
    --cli        Launch with command-line interface
"""

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_gui_client(username: str = None, server_host: str = 'localhost', server_port: int = 9000):
    """Run the GUI client."""
    try:
        from client.ui.client_gui import ClientMainWindow
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("[ERROR] PyQt6 not installed. Install with: pip install PyQt6")
        sys.exit(1)
    
    app = QApplication(sys.argv)
    
    # Create and show window
    window = ClientMainWindow(server_host, server_port)
    
    window.show()
    
    # Connect to server - username will be asked in dialog
    if not window.connect_to_server():
        print("[ERROR] Failed to connect to server")
        sys.exit(1)
    
    # Run application
    sys.exit(app.exec())


def run_cli_client(username: str = None, server_host: str = 'localhost', server_port: int = 9000):
    """Run the CLI client."""
    import asyncio
    from client.main_client import CollaborationClient
    
    if not username:
        username = input("Enter username: ").strip() or "anonymous"
    
    client = CollaborationClient(
        host=server_host,
        port=server_port,
        username=username,
        audio_port=11000,
        video_port=10000
    )
    
    try:
        asyncio.run(client.interactive_mode())
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    except Exception as e:
        from client.utils.logger import logger
        logger.log_error("client", e)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='LAN Collaboration Client')
    parser.add_argument('--username', type=str, default=None,
                       help='Username for chat (default: will be asked in GUI)')
    parser.add_argument('--server-ip', type=str, default='localhost',
                       help='Server IP address (default: localhost)')
    parser.add_argument('--port', type=int, default=9000,
                       help='Server port (default: 9000)')
    parser.add_argument('--cli', action='store_true',
                       help='Run in command-line mode (GUI is default)')
    
    args = parser.parse_args()
    
    # Always use GUI unless --cli is specified
    use_gui = not args.cli
    
    if use_gui:
        run_gui_client(args.username, args.server_ip, args.port)
    else:
        run_cli_client(args.username, args.server_ip, args.port)


if __name__ == "__main__":
    main()

