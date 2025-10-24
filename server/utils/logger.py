"""
Server logging module.

This module handles server-side logging functionality.
"""

import logging
import os
from datetime import datetime
from pathlib import Path


class ServerLogger:
    """Server logging class."""
    
    def __init__(self, logs_dir: str = 'logs', log_level: int = logging.INFO):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(exist_ok=True)
        
        # Set up main logger
        self.logger = logging.getLogger('collaboration_server')
        self.logger.setLevel(log_level)
        
        # Remove existing handlers
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(console_handler)
        
        # Set up file paths
        self.transfer_log_path = self.logs_dir / 'file_transfers.log'
        self.chat_log_path = self.logs_dir / 'chat_history.log'
        self.screen_share_log_path = self.logs_dir / 'screen_sharing.log'
    
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
    
    def log_connection(self, addr: tuple, uid: int):
        """Log client connection."""
        self.info(f"New connection from {addr}, assigned uid={uid}")
    
    def log_login(self, username: str, uid: int):
        """Log user login."""
        self.info(f"User '{username}' logged in with uid={uid}")
    
    def log_disconnect(self, username: str, uid: int):
        """Log user disconnect."""
        self.info(f"User {username} (uid={uid}) disconnected")
    
    def log_chat(self, username: str, uid: int, message: str):
        """Log chat message."""
        self.info(f"Chat from {username} (uid={uid}): {message}")
        self._write_to_file(self.chat_log_path, f"{datetime.now().isoformat()} | {username} (uid={uid}) | {message}")
    
    def log_broadcast(self, username: str, uid: int, message: str):
        """Log broadcast message."""
        self.info(f"📢 BROADCAST from {username} (uid={uid}): {message}")
        self._write_to_file(self.chat_log_path, f"{datetime.now().isoformat()} | [BROADCAST] {username} (uid={uid}) | {message}")
    
    def log_unicast(self, from_username: str, from_uid: int, to_username: str, to_uid: int, message: str):
        """Log unicast message."""
        self.info(f"📨 UNICAST from {from_username} (uid={from_uid}) to {to_username} (uid={to_uid}): {message}")
        self._write_to_file(self.chat_log_path, f"{datetime.now().isoformat()} | [UNICAST {from_username}→{to_username}] {from_username} (uid={from_uid}) | {message}")
    
    def log_file_upload(self, filename: str, size: int, uploader: str, fid: str):
        """Log file upload."""
        self.info(f"✓ FILE UPLOAD SUCCESS: '{filename}' ({size} bytes)")
        self.info(f"  Uploader: {uploader}")
        self.info(f"  File ID: {fid}")
        self._write_to_file(self.transfer_log_path, f"{datetime.now().isoformat()} | UPLOAD | {filename} | USER: {uploader} | SIZE: {size} bytes | FID: {fid}")
    
    def log_file_download(self, filename: str, size: int, uploader: str, requester: str, fid: str):
        """Log file download."""
        self.info(f"✓ FILE DOWNLOAD SUCCESS: '{filename}' ({size} bytes)")
        self.info(f"  Transfer: {uploader} → {requester}")
        self._write_to_file(self.transfer_log_path, f"{datetime.now().isoformat()} | DOWNLOAD | {filename} | FROM: {uploader} | TO: {requester} | SIZE: {size} bytes | FID: {fid}")
    
    def log_file_request(self, filename: str, requester: str, uploader: str, fid: str):
        """Log file request."""
        self.info(f"📥 FILE REQUEST: {requester} wants '{filename}' from {uploader}")
        self.info(f"  File ID: {fid}")
    
    def log_screen_share_start(self, username: str, uid: int, topic: str, presenter_port: int, viewer_port: int):
        """Log screen share start."""
        self.info(f"🎬 SCREEN SHARE STARTING: {username} (uid={uid}) - {topic}")
        self.info(f"  Presenter port: {presenter_port}")
        self.info(f"  Viewer port: {viewer_port}")
        self._write_to_file(self.screen_share_log_path, f"{datetime.now().isoformat()} | START | {username} (uid={uid}) | Topic: {topic} | Presenter Port: {presenter_port} | Viewer Port: {viewer_port}")
    
    def log_screen_share_stop(self, username: str, uid: int, viewers_count: int):
        """Log screen share stop."""
        self.info(f"🎬 SCREEN SHARE STOPPED: {username} (uid={uid})")
        self._write_to_file(self.screen_share_log_path, f"{datetime.now().isoformat()} | STOP | {username} (uid={uid}) | Duration: presentation ended | Viewers: {viewers_count}")
    
    def log_viewer_join(self, presenter_username: str, presenter_uid: int, viewer_addr: tuple):
        """Log viewer join."""
        self._write_to_file(self.screen_share_log_path, f"{datetime.now().isoformat()} | VIEWER_JOIN | {presenter_username} (uid={presenter_uid}) | Viewer from {viewer_addr}")
    
    def log_error(self, operation: str, error: Exception):
        """Log error with operation context."""
        self.error(f"Error in {operation}: {error}")
    
    def _write_to_file(self, file_path: Path, content: str):
        """Write content to log file."""
        try:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(content + '\n')
        except Exception as e:
            self.error(f"Failed to write to log file {file_path}: {e}")


# Global logger instance
logger = ServerLogger()
