"""
Protocol definitions for LAN Multi-User Collaboration System.

This module defines the message structures and data formats used in communication
between client and server components.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class UserInfo:
    """User information structure."""
    uid: int
    username: str
    joined_at: str


@dataclass
class FileInfo:
    """File metadata structure."""
    fid: str
    filename: str
    size: int
    uploader: str
    uploader_uid: int
    path: str
    uploaded_at: str


@dataclass
class ChatMessage:
    """Chat message structure."""
    type: str
    uid: int
    username: str
    text: str
    timestamp: str


@dataclass
class BroadcastMessage:
    """Broadcast message structure."""
    type: str
    uid: int
    username: str
    text: str
    timestamp: str


@dataclass
class UnicastMessage:
    """Private message structure."""
    type: str
    from_uid: int
    from_username: str
    to_uid: int
    to_username: str
    text: str
    timestamp: str


@dataclass
class FileOffer:
    """File offer structure."""
    type: str
    fid: str
    filename: str
    size: int


@dataclass
class FileRequest:
    """File request structure."""
    type: str
    fid: str


@dataclass
class ScreenShareSession:
    """Screen sharing session structure."""
    presenter_uid: int
    presenter_username: str
    topic: str
    presenter_port: int
    viewer_port: int
    start_time: str


def create_login_message(username: str) -> Dict[str, Any]:
    """Create a login message."""
    return {
        "type": "login",
        "username": username
    }


def create_heartbeat_message() -> Dict[str, Any]:
    """Create a heartbeat message."""
    return {
        "type": "heartbeat",
        "timestamp": datetime.now().isoformat()
    }


def create_chat_message(text: str) -> Dict[str, Any]:
    """Create a chat message."""
    return {
        "type": "chat",
        "text": text
    }


def create_broadcast_message(text: str) -> Dict[str, Any]:
    """Create a broadcast message."""
    return {
        "type": "broadcast",
        "text": text
    }


def create_unicast_message(target_uid: int, text: str) -> Dict[str, Any]:
    """Create a unicast message."""
    return {
        "type": "unicast",
        "target_uid": target_uid,
        "text": text
    }


def create_file_offer_message(fid: str, filename: str, size: int) -> Dict[str, Any]:
    """Create a file offer message."""
    return {
        "type": "file_offer",
        "fid": fid,
        "filename": filename,
        "size": size
    }


def create_file_request_message(fid: str) -> Dict[str, Any]:
    """Create a file request message."""
    return {
        "type": "file_request",
        "fid": fid
    }


def create_present_start_message(topic: str) -> Dict[str, Any]:
    """Create a present start message."""
    from common.constants import MessageTypes
    return {
        "type": MessageTypes.PRESENT_START,
        "topic": topic
    }


def create_present_stop_message() -> Dict[str, Any]:
    """Create a present stop message."""
    from common.constants import MessageTypes
    return {
        "type": MessageTypes.PRESENT_STOP
    }


def create_logout_message() -> Dict[str, Any]:
    """Create a logout message."""
    return {
        "type": "logout"
    }


def create_get_history_message() -> Dict[str, Any]:
    """Create a get history message."""
    return {
        "type": "get_history"
    }


def create_error_message(message: str) -> Dict[str, Any]:
    """Create an error message."""
    return {
        "type": "error",
        "message": message
    }


def create_login_success_message(uid: int, username: str) -> Dict[str, Any]:
    """Create a login success message."""
    return {
        "type": "login_success",
        "uid": uid,
        "username": username
    }


def create_participant_list_message(participants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a participant list message."""
    return {
        "type": "participant_list",
        "participants": participants
    }


def create_history_message(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a history message."""
    return {
        "type": "history",
        "messages": messages,
        "count": len(messages)
    }


def create_user_joined_message(uid: int, username: str) -> Dict[str, Any]:
    """Create a user joined message."""
    return {
        "type": "user_joined",
        "uid": uid,
        "username": username,
        "timestamp": datetime.now().isoformat()
    }


def create_user_left_message(uid: int, username: str) -> Dict[str, Any]:
    """Create a user left message."""
    return {
        "type": "user_left",
        "uid": uid,
        "username": username,
        "timestamp": datetime.now().isoformat()
    }


def create_heartbeat_ack_message() -> Dict[str, Any]:
    """Create a heartbeat acknowledgment message."""
    return {
        "type": "heartbeat_ack",
        "timestamp": datetime.now().isoformat()
    }


def create_file_upload_port_message(fid: str, port: int) -> Dict[str, Any]:
    """Create a file upload port message."""
    return {
        "type": "file_upload_port",
        "fid": fid,
        "port": port
    }


def create_file_download_port_message(fid: str, filename: str, size: int, port: int) -> Dict[str, Any]:
    """Create a file download port message."""
    return {
        "type": "file_download_port",
        "fid": fid,
        "filename": filename,
        "size": size,
        "port": port
    }


def create_file_available_message(fid: str, filename: str, size: int, uploader: str) -> Dict[str, Any]:
    """Create a file available message."""
    return {
        "type": "file_available",
        "fid": fid,
        "filename": filename,
        "size": size,
        "uploader": uploader,
        "timestamp": datetime.now().isoformat()
    }


def create_screen_share_ports_message(presenter_port: int, viewer_port: int) -> Dict[str, Any]:
    """Create a screen share ports message."""
    return {
        "type": "screen_share_ports",
        "presenter_port": presenter_port,
        "viewer_port": viewer_port
    }


def create_present_start_broadcast_message(uid: int, username: str, topic: str, viewer_port: int) -> Dict[str, Any]:
    """Create a present start broadcast message."""
    from common.constants import MessageTypes
    return {
        "type": MessageTypes.PRESENT_START_BROADCAST,
        "uid": uid,
        "username": username,
        "topic": topic,
        "viewer_port": viewer_port,
        "timestamp": datetime.now().isoformat()
    }


def create_present_stop_broadcast_message(uid: int, username: str) -> Dict[str, Any]:
    """Create a present stop broadcast message."""
    from common.constants import MessageTypes
    return {
        "type": MessageTypes.PRESENT_STOP_BROADCAST,
        "uid": uid,
        "username": username,
        "timestamp": datetime.now().isoformat()
    }


def create_unicast_sent_message(to_uid: int, to_username: str) -> Dict[str, Any]:
    """Create a unicast sent confirmation message."""
    return {
        "type": "unicast_sent",
        "to_uid": to_uid,
        "to_username": to_username,
        "message": "Message sent successfully"
    }
