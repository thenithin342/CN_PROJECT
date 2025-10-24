"""
Server configuration module.

This module handles server-side configuration settings.
"""

from common.constants import DEFAULT_SERVER_HOST, DEFAULT_PORT, DEFAULT_EPHEMERAL_PORT_START, UPLOAD_DIR, LOG_DIR


class ServerConfig:
    """Server configuration class."""
    
    def __init__(self, host: str = DEFAULT_SERVER_HOST, port: int = DEFAULT_PORT, upload_dir: str = UPLOAD_DIR):
        self.host = host
        self.port = port
        self.upload_dir = upload_dir
        
        # Logging configuration
        self.logs_dir = LOG_DIR
        
        # File transfer settings
        self.chunk_size = 8192
        self.progress_log_interval = 1024 * 1024  # 1MB
        self.transfer_timeout = 300  # 5 minutes
        
        # Port management
        self.next_ephemeral_port = DEFAULT_EPHEMERAL_PORT_START
        
        # Chat settings
        self.max_chat_history = 500
        
        # Connection settings
        self.heartbeat_interval = 10  # seconds
    
    def get_ephemeral_port(self) -> int:
        """Allocate an ephemeral port for file transfer."""
        port = self.next_ephemeral_port
        self.next_ephemeral_port += 1
        return port
    
    def get_connection_info(self):
        """Get connection information."""
        return {
            'host': self.host,
            'port': self.port
        }
    
    def get_file_settings(self):
        """Get file transfer settings."""
        return {
            'upload_dir': self.upload_dir,
            'chunk_size': self.chunk_size,
            'progress_log_interval': self.progress_log_interval,
            'transfer_timeout': self.transfer_timeout
        }
    
    def get_log_settings(self):
        """Get logging settings."""
        return {
            'logs_dir': self.logs_dir
        }
