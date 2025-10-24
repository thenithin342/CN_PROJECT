"""
Client GUI module.

This module handles client-side user interface components.
"""

import asyncio
import sys
from typing import Optional, Callable

from client.screen.screen_viewer import ScreenViewerWindow


class ClientGUI:
    """Client-side GUI functionality."""
    
    def __init__(self):
        self.message_handler: Optional[Callable] = None
    
    def set_message_handler(self, handler: Callable):
        """Set the message handler for incoming messages."""
        self.message_handler = handler
    
    async def handle_user_input(self, user_input: str, client_instance) -> bool:
        """Handle user input - commands or chat messages."""
        if user_input.startswith('/'):
            # Parse command
            parts = user_input.split(maxsplit=2)
            command = parts[0].lower()
            
            if command == '/help':
                self._show_help()
                return True
            
            elif command == '/upload':
                if len(parts) < 2:
                    print("[ERROR] Usage: /upload <file_path>")
                else:
                    file_path = parts[1]
                    await client_instance.file_client.upload_file(file_path)
                return True
            
            elif command == '/download':
                if len(parts) < 2:
                    print("[ERROR] Usage: /download <fid> [save_path]")
                    print("[INFO] Files are saved to downloads/ directory by default")
                else:
                    fid = parts[1]
                    save_path = parts[2] if len(parts) > 2 else None
                    if save_path:
                        client_instance.file_client.pending_downloads[fid] = save_path
                    await client_instance.file_client.download_file(fid, save_path)
                return True
            
            elif command == '/present':
                if not hasattr(client_instance, 'screen_presenter'):
                    print("[ERROR] Screen sharing not available")
                else:
                    await client_instance.screen_presenter.start_presentation()
                return True
            
            elif command == '/view':
                if not hasattr(client_instance, 'screen_viewer'):
                    print("[ERROR] Screen sharing not available")
                elif not client_instance.screen_viewer.current_presentation:
                    print("[ERROR] No active presentation to view")
                else:
                    presentation = client_instance.screen_viewer.current_presentation
                    await client_instance.screen_viewer.view_presentation(
                        presentation['viewer_port'],
                        presentation['username']
                    )
                return True
            
            elif command == '/stopshare':
                if hasattr(client_instance, 'screen_presenter'):
                    await client_instance.screen_presenter.stop_presentation()
                return True
            
            elif command == '/broadcast':
                if len(parts) < 2:
                    print("[ERROR] Usage: /broadcast <message>")
                else:
                    message = parts[1]
                    await client_instance.chat_client.send_broadcast(message)
                return True
            
            elif command == '/unicast':
                if len(parts) < 3:
                    print("[ERROR] Usage: /unicast <uid> <message>")
                    print("[INFO] Use participant list to see available UIDs")
                else:
                    try:
                        target_uid = int(parts[1])
                        message = parts[2]
                        await client_instance.chat_client.send_unicast(target_uid, message)
                    except ValueError:
                        print("[ERROR] UID must be a number")
                return True
            
            else:
                print(f"[ERROR] Unknown command: {command}. Type /help for help.")
                return True
        else:
            # Regular chat message
            await client_instance.chat_client.send_chat(user_input)
            return True
    
    def _show_help(self):
        """Show help information."""
        print("\n[HELP] Available commands:")
        print("  /upload <file_path>        - Upload a file")
        print("  /download <fid> [path]     - Download a file by fid")
        print("                               (saves to downloads/ by default)")
        print("  /present                   - Start screen sharing")
        print("  /view                      - View current presentation")
        print("  /stopshare                 - Stop your screen sharing")
        print("  /broadcast <message>       - Send message to all users")
        print("  /unicast <uid> <message>   - Send private message to user")
        print("  /help                      - Show this help")
        print("  (anything else)            - Send as chat message\n")
    
    def show_connection_info(self, host: str, port: int):
        """Show connection information."""
        print(f"[INFO] Connected to {host}:{port}")
    
    def show_login_info(self, username: str):
        """Show login information."""
        print(f"[INFO] Logging in as '{username}'...")
    
    def show_login_success(self, username: str, uid: int):
        """Show login success."""
        print(f"[SUCCESS] Logged in as '{username}' with uid={uid}")
    
    def show_participants(self, participants: list):
        """Show participant list."""
        print(f"[INFO] Current participants ({len(participants)}):")
        for p in participants:
            print(f"  - {p.get('username')} (uid={p.get('uid')})")
    
    def show_user_joined(self, username: str, uid: int, current_uid: int):
        """Show user joined notification."""
        if uid != current_uid:
            print(f"[EVENT] User '{username}' joined (uid={uid})")
    
    def show_user_left(self, username: str, uid: int):
        """Show user left notification."""
        print(f"[EVENT] User '{username}' left (uid={uid})")
    
    def show_interactive_mode_info(self):
        """Show interactive mode information."""
        print("[INFO] Type messages to chat (Ctrl+C to exit)")
        print("[INFO] Commands: /upload /download /present /view /stopshare /help")
