"""
Chat server module.

This module handles server-side chat messaging functionality.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

from common.constants import MessageTypes, MAX_CHAT_HISTORY
from common.protocol_definitions import (
    create_login_success_message, create_participant_list_message,
    create_history_message, create_user_joined_message, create_user_left_message,
    create_heartbeat_ack_message, create_error_message
)
from server.utils.logger import logger


class ChatServer:
    """Server-side chat functionality."""
    
    def __init__(self):
        self.participants: Dict[int, dict] = {}  # uid -> user info
        self.chat_history = deque(maxlen=MAX_CHAT_HISTORY)  # Keep last 500 chat messages
        self.next_uid = 1
        self.lock = asyncio.Lock()  # Protect shared state
    
    async def broadcast(self, message: dict, clients: Dict[int, asyncio.StreamWriter], exclude_uid: int = None):
        """
        Send a JSON message to all connected clients.
        Optionally exclude a specific client by uid.
        """
        msg_data = json.dumps(message).encode('utf-8') + b'\n'
        disconnected = []
        
        async with self.lock:
            for uid, writer in clients.items():
                if exclude_uid is not None and uid == exclude_uid:
                    continue
                try:
                    writer.write(msg_data)
                    await writer.drain()
                except Exception as e:
                    logger.error(f"Failed to broadcast to uid={uid}: {e}")
                    disconnected.append(uid)
        
        return disconnected
    
    async def send_message(self, uid: int, message: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Send a JSON message to a specific client."""
        async with self.lock:
            writer = clients.get(uid)
            if writer is None:
                return False
        
        try:
            msg_data = json.dumps(message).encode('utf-8') + b'\n'
            writer.write(msg_data)
            await writer.drain()
            return True
        except Exception as e:
            logger.error(f"Failed to send to uid={uid}: {e}")
            return False
    
    async def handle_login(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Process login message."""
        username = data.get('username', f'user_{uid}')
        
        async with self.lock:
            self.participants[uid] = {
                "uid": uid,
                "username": username,
                "joined_at": datetime.now().isoformat()
            }
        
        logger.log_login(username, uid)
        
        # Send confirmation to the client
        await self.send_message(uid, create_login_success_message(uid, username), clients)
        
        # Get current participant list
        async with self.lock:
            participants_list = list(self.participants.values())
        
        # Broadcast user_joined to all other clients (but not the new user)
        await self.broadcast(create_user_joined_message(uid, username), clients, exclude_uid=uid)
        
        # Broadcast updated participant list to ALL clients (including the new user)
        await self.broadcast(create_participant_list_message(participants_list), clients)
    
    async def handle_heartbeat(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Process heartbeat message."""
        logger.debug(f"Heartbeat from uid={uid}")
        
        # Get current participant list
        async with self.lock:
            participants_list = list(self.participants.values())
        
        # Respond with heartbeat_ack
        await self.send_message(uid, create_heartbeat_ack_message(), clients)
        
        # Also send updated participant list
        await self.send_message(uid, create_participant_list_message(participants_list), clients)
    
    async def handle_chat(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Process chat message and broadcast to all."""
        # Support both "text" and "message" fields for compatibility
        message_text = data.get('text', data.get('message', ''))
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        logger.log_chat(username, uid, message_text)
        
        # Create stamped chat message
        chat_message = {
            "type": MessageTypes.CHAT,
            "uid": uid,
            "username": username,
            "text": message_text,
            "timestamp": datetime.now().isoformat()
        }
        
        # Store in chat history
        async with self.lock:
            self.chat_history.append(chat_message)
        
        # Broadcast chat message to all clients
        await self.broadcast(chat_message, clients)
    
    async def handle_broadcast(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Process broadcast message and send to all users."""
        message_text = data.get('text', data.get('message', ''))
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        logger.log_broadcast(username, uid, message_text)
        
        # Create broadcast message
        broadcast_message = {
            "type": MessageTypes.BROADCAST,
            "uid": uid,
            "username": username,
            "text": message_text,
            "timestamp": datetime.now().isoformat()
        }
        
        # Store in chat history
        async with self.lock:
            self.chat_history.append(broadcast_message)
        
        # Broadcast to all clients
        await self.broadcast(broadcast_message, clients)
    
    async def handle_unicast(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Process unicast message and send to specific user."""
        message_text = data.get('text', data.get('message', ''))
        target_uid = data.get('target_uid')
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        if not target_uid:
            await self.send_message(uid, create_error_message("Missing target_uid for unicast"), clients)
            return
        
        # Check if target user exists
        async with self.lock:
            if target_uid not in self.participants:
                await self.send_message(uid, create_error_message(f"User with uid={target_uid} not found"), clients)
                return
            
            target_username = self.participants[target_uid]['username']
        
        logger.log_unicast(username, uid, target_username, target_uid, message_text)
        
        # Create unicast message
        unicast_message = {
            "type": MessageTypes.UNICAST,
            "from_uid": uid,
            "from_username": username,
            "to_uid": target_uid,
            "to_username": target_username,
            "text": message_text,
            "timestamp": datetime.now().isoformat()
        }
        
        # Store in chat history
        async with self.lock:
            self.chat_history.append(unicast_message)
        
        # Send to target user
        await self.send_message(target_uid, unicast_message, clients)
        
        # Send confirmation to sender
        from common.protocol_definitions import create_unicast_sent_message
        await self.send_message(uid, create_unicast_sent_message(target_uid, target_username), clients)
    
    async def handle_logout(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Process logout message."""
        logger.info(f"Logout request from uid={uid}")
        await self.disconnect_client(uid, clients)
    
    async def handle_get_history(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Send chat history to requesting client."""
        logger.info(f"Chat history requested by uid={uid}")
        
        # Get chat history as a list (thread-safe copy)
        async with self.lock:
            history_list = list(self.chat_history)
        
        # Send history to the requesting client
        await self.send_message(uid, create_history_message(history_list), clients)
    
    async def disconnect_client(self, uid: int, clients: Dict[int, asyncio.StreamWriter]):
        """Remove client and notify others."""
        username = None
        participants_list = None
        
        async with self.lock:
            if uid in clients:
                writer = clients[uid]
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                del clients[uid]
            
            if uid in self.participants:
                user_info = self.participants[uid]
                username = user_info.get('username', 'unknown')
                del self.participants[uid]
                logger.log_disconnect(username, uid)
                
                # Get updated participant list
                participants_list = list(self.participants.values())
        
        # Perform broadcast operations outside the lock to avoid deadlock
        if username is not None:
            # Broadcast user_left event
            await self.broadcast(create_user_left_message(uid, username), clients)
            
            # Broadcast updated participant list to all clients
            await self.broadcast(create_participant_list_message(participants_list), clients)
    
    def get_next_uid(self) -> int:
        """Get the next available UID."""
        uid = self.next_uid
        self.next_uid += 1
        return uid
    
    def get_participant_count(self) -> int:
        """Get the number of current participants."""
        return len(self.participants)
