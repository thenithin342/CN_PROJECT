"""
Shared constants for LAN Multi-User Collaboration System.

This module contains all constants used across client and server components.
"""

# Network Configuration
DEFAULT_HOST = 'localhost'
DEFAULT_SERVER_HOST = '0.0.0.0'
DEFAULT_PORT = 9000
DEFAULT_EPHEMERAL_PORT_START = 10000

# Buffer Sizes
CHUNK_SIZE = 8192
PROGRESS_LOG_INTERVAL = 1024 * 1024  # Log progress every 1MB

# Timeouts
HEARTBEAT_INTERVAL = 10  # seconds
TRANSFER_TIMEOUT = 300  # 5 minutes in seconds

# File Transfer
UPLOAD_DIR = 'uploads'
DOWNLOAD_DIR = 'downloads'

# Screen Sharing
DEFAULT_FPS = 3
DEFAULT_QUALITY = 70
DEFAULT_SCALE = 0.5
FRAME_HEADER_SIZE = 4  # bytes for frame length header

# Chat History
MAX_CHAT_HISTORY = 500

# Logging
LOG_DIR = 'logs'
CHAT_LOG_FILE = 'chat_history.log'
TRANSFER_LOG_FILE = 'file_transfers.log'
SCREEN_SHARE_LOG_FILE = 'screen_sharing.log'

# Message Types
class MessageTypes:
    # Client to Server
    LOGIN = 'login'
    HEARTBEAT = 'heartbeat'
    CHAT = 'chat'
    BROADCAST = 'broadcast'
    UNICAST = 'unicast'
    GET_HISTORY = 'get_history'
    FILE_OFFER = 'file_offer'
    FILE_REQUEST = 'file_request'
    PRESENT_START = 'present_start'
    PRESENT_STOP = 'present_stop'
    LOGOUT = 'logout'
    
    # Server to Client
    LOGIN_SUCCESS = 'login_success'
    PARTICIPANT_LIST = 'participant_list'
    HISTORY = 'history'
    USER_JOINED = 'user_joined'
    USER_LEFT = 'user_left'
    HEARTBEAT_ACK = 'heartbeat_ack'
    FILE_UPLOAD_PORT = 'file_upload_port'
    FILE_DOWNLOAD_PORT = 'file_download_port'
    FILE_AVAILABLE = 'file_available'
    SCREEN_SHARE_PORTS = 'screen_share_ports'
    PRESENT_START = 'present_start'
    PRESENT_STOP = 'present_stop'
    UNICAST_SENT = 'unicast_sent'
    ERROR = 'error'
