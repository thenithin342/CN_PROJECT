"""
Chat client module.

This module handles client-side chat messaging functionality.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, Callable

from common.constants import MessageTypes
from common.protocol_definitions import (
    create_chat_message, create_broadcast_message, create_unicast_message,
    create_get_history_message
)


class ChatClient:
    """Client-side chat functionality."""
    
    def __init__(self, writer: Optional[asyncio.StreamWriter] = None):
        self.writer = writer
        self.message_handler: Optional[Callable] = None
    
    def set_writer(self, writer: asyncio.StreamWriter):
        """Set the writer for sending messages."""
        self.writer = writer
    
    def set_message_handler(self, handler: Callable):
        """Set the message handler for incoming messages."""
        self.message_handler = handler
    
    async def send_message(self, message: dict) -> bool:
        """Send a JSON message to the server."""
        if not self.writer:
            print("[ERROR] Not connected to server")
            return False
        
        try:
            msg_data = json.dumps(message).encode('utf-8') + b'\n'
            self.writer.write(msg_data)
            await self.writer.drain()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")
            return False
    
    async def send_chat(self, message: str) -> bool:
        """Send a chat message."""
        chat_msg = create_chat_message(message)
        return await self.send_message(chat_msg)
    
    async def send_broadcast(self, message: str) -> bool:
        """Send a broadcast message to all users."""
        broadcast_msg = create_broadcast_message(message)
        return await self.send_message(broadcast_msg)
    
    async def send_unicast(self, target_uid: int, message: str) -> bool:
        """Send a private message to a specific user."""
        unicast_msg = create_unicast_message(target_uid, message)
        return await self.send_message(unicast_msg)
    
    async def request_history(self) -> bool:
        """Request chat history from server."""
        history_msg = create_get_history_message()
        return await self.send_message(history_msg)
    
    async def handle_message(self, message: dict):
        """Handle different types of chat messages from server."""
        msg_type = message.get('type', '')
        
        if msg_type == MessageTypes.CHAT:
            await self._handle_chat_message(message)
        elif msg_type == MessageTypes.BROADCAST:
            await self._handle_broadcast_message(message)
        elif msg_type == MessageTypes.UNICAST:
            await self._handle_unicast_message(message)
        elif msg_type == MessageTypes.HISTORY:
            await self._handle_history_message(message)
        elif msg_type == MessageTypes.UNICAST_SENT:
            await self._handle_unicast_sent_message(message)
    
    async def _handle_chat_message(self, message: dict):
        """Handle incoming chat message."""
        uid = message.get('uid')
        username = message.get('username')
        text = message.get('text', message.get('message', ''))
        timestamp = message.get('timestamp', '')
        
        # Don't echo our own messages
        if hasattr(self, 'uid') and uid != self.uid:
            print(f"[CHAT] {username}: {text}")
    
    async def _handle_broadcast_message(self, message: dict):
        """Handle incoming broadcast message."""
        uid = message.get('uid')
        username = message.get('username')
        text = message.get('text', message.get('message', ''))
        timestamp = message.get('timestamp', '')
        
        # Don't echo our own broadcasts
        if hasattr(self, 'uid') and uid != self.uid:
            print(f"📢 [BROADCAST] {username}: {text}")
    
    async def _handle_unicast_message(self, message: dict):
        """Handle incoming unicast message."""
        from_uid = message.get('from_uid')
        from_username = message.get('from_username')
        to_uid = message.get('to_uid')
        to_username = message.get('to_username')
        text = message.get('text', message.get('message', ''))
        timestamp = message.get('timestamp', '')
        
        # This message is for us
        if hasattr(self, 'uid') and to_uid == self.uid:
            print(f"📨 [PRIVATE] {from_username} → {to_username}: {text}")
    
    async def _handle_history_message(self, message: dict):
        """Handle chat history response."""
        messages = message.get('messages', [])
        count = message.get('count', 0)
        
        if count > 0:
            print(f"\n[HISTORY] Loading {count} previous message(s):")
            print("-" * 50)
            # Display messages in chronological order
            for msg in messages:
                uid = msg.get('uid')
                username = msg.get('username', 'unknown')
                text = msg.get('text', msg.get('message', ''))
                timestamp = msg.get('timestamp', '')
                print(f"[{timestamp[:19]}] {username}: {text}")
            print("-" * 50)
        else:
            print("[HISTORY] No previous messages")
    
    async def _handle_unicast_sent_message(self, message: dict):
        """Handle unicast sent confirmation."""
        to_uid = message.get('to_uid')
        to_username = message.get('to_username')
        print(f"✓ [SENT] Private message delivered to {to_username} (uid={to_uid})")
    
    def set_uid(self, uid: int):
        """Set the client's UID for message filtering."""
        self.uid = uid
