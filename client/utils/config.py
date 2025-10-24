"""
Client configuration module.

This module handles client-side configuration settings.
"""

from common.constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_FPS, DEFAULT_QUALITY, DEFAULT_SCALE


class ClientConfig:
    """Client configuration class."""
    
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, username: str = None):
        self.host = host
        self.port = port
        self.username = username or f"user_{id(self) % 10000}"
        
        # Screen sharing settings
        self.screen_fps = DEFAULT_FPS
        self.screen_quality = DEFAULT_QUALITY
        self.screen_scale = DEFAULT_SCALE
        
        # File transfer settings
        self.chunk_size = 8192
        self.progress_log_interval = 1024 * 1024  # 1MB
        
        # Connection settings
        self.heartbeat_interval = 10  # seconds
    
    def update_screen_settings(self, fps: int = None, quality: int = None, scale: float = None):
        """Update screen sharing settings."""
        if fps is not None:
            self.screen_fps = fps
        if quality is not None:
            self.screen_quality = quality
        if scale is not None:
            self.screen_scale = scale
    
    def get_connection_info(self):
        """Get connection information."""
        return {
            'host': self.host,
            'port': self.port,
            'username': self.username
        }
    
    def get_screen_settings(self):
        """Get screen sharing settings."""
        return {
            'fps': self.screen_fps,
            'quality': self.screen_quality,
            'scale': self.screen_scale
        }
