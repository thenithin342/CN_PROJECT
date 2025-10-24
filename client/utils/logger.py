"""
Client logging module.

This module handles client-side logging functionality.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


class ClientLogger:
    """Client logging class."""
    
    def __init__(self, log_level: int = logging.INFO):
        self.logger = logging.getLogger('collaboration_client')
        self.logger.setLevel(log_level)
        
        # Remove existing handlers
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(console_handler)
    
    def info(self, message: str):
        """Log info message."""
        self.logger.info(message)
    
    def error(self, message: str):
        """Log error message."""
        self.logger.error(message)
    
    def warning(self, message: str):
        """Log warning message."""
        self.logger.warning(message)
    
    def debug(self, message: str):
        """Log debug message."""
        self.logger.debug(message)
    
    def log_connection(self, host: str, port: int, success: bool):
        """Log connection attempt."""
        status = "Connected" if success else "Failed to connect"
        self.info(f"{status} to {host}:{port}")
    
    def log_login(self, username: str, uid: int, success: bool):
        """Log login attempt."""
        status = "Logged in" if success else "Login failed"
        self.info(f"{status} as '{username}' with uid={uid}")
    
    def log_chat_sent(self, message: str):
        """Log chat message sent."""
        self.info(f"Chat sent: {message}")
    
    def log_file_upload(self, filename: str, size: int, fid: str):
        """Log file upload attempt."""
        self.info(f"Uploading file: {filename} ({size} bytes, fid={fid})")
    
    def log_file_download(self, filename: str, fid: str):
        """Log file download attempt."""
        self.info(f"Downloading file: {filename} (fid={fid})")
    
    def log_screen_share(self, action: str, details: str = ""):
        """Log screen sharing activity."""
        if details:
            self.info(f"Screen share {action}: {details}")
        else:
            self.info(f"Screen share {action}")
    
    def show_login_info(self, username: str):
        """Show login information."""
        self.info(f"[INFO] Logging in as '{username}'...")
    
    def show_login_success(self, username: str, uid: int):
        """Show login success."""
        self.info(f"[SUCCESS] Logged in as '{username}' with uid={uid}")
    
    def show_participants(self, participants: list):
        """Show participant list."""
        self.info(f"[INFO] Current participants ({len(participants)}):")
        for p in participants:
            self.info(f"  - {p.get('username')} (uid={p.get('uid')})")
    
    def show_user_joined(self, username: str, uid: int, current_uid: int):
        """Show user joined notification."""
        if uid != current_uid:
            self.info(f"[EVENT] User '{username}' joined (uid={uid})")
    
    def show_user_left(self, username: str, uid: int):
        """Show user left notification."""
        self.info(f"[EVENT] User '{username}' left (uid={uid})")
    
    def show_interactive_mode_info(self):
        """Show interactive mode information."""
        self.info("[INFO] Type messages to chat (Ctrl+C to exit)")
        self.info("[INFO] Commands: /upload /download /present /view /stopshare /help")
    
    def log_error(self, operation: str, error: Exception):
        """Log error with operation context."""
        self.error(f"Error in {operation}: {error}")


# Global logger instance
logger = ClientLogger()
