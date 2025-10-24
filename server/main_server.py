#!/usr/bin/env python3
"""
LAN Multi-User Collaboration Server - Main Entry Point

This is the main entry point for the server application.
It integrates all server modules (chat, files, screen sharing) into a cohesive server.
"""

import asyncio
import json
from typing import Dict

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.chat.chat_server import ChatServer
from server.files.file_server import FileServer
from server.screen.screen_server import ScreenServer
from server.utils.config import ServerConfig
from server.utils.logger import logger
from common.constants import MessageTypes


class CollaborationServer:
    """Main server class that integrates all functionality."""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 9000, upload_dir: str = 'uploads'):
        self.config = ServerConfig(host, port, upload_dir)
        self.clients: Dict[int, asyncio.StreamWriter] = {}  # uid -> writer
        
        # Initialize modules
        self.chat_server = ChatServer()
        self.file_server = FileServer(upload_dir, self.chat_server.participants, self.broadcast)
        self.screen_server = ScreenServer(self.chat_server.participants)
    
    async def broadcast(self, message: dict, exclude_uid: int = None):
        """Send a JSON message to all connected clients."""
        return await self.chat_server.broadcast(message, self.clients, exclude_uid)
    
    async def send_message(self, uid: int, message: dict):
        """Send a JSON message to a specific client."""
        return await self.chat_server.send_message(uid, message, self.clients)
    
    async def disconnect_client(self, uid: int):
        """Remove client and notify others."""
        await self.chat_server.disconnect_client(uid, self.clients)
        # Remove from our client list
        if uid in self.clients:
            del self.clients[uid]
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle individual client connection."""
        addr = writer.get_extra_info('peername')
        
        # Assign uid to client
        uid = self.chat_server.get_next_uid()
        self.clients[uid] = writer
        
        logger.log_connection(addr, uid)
        
        try:
            while True:
                # Read line-delimited JSON
                data = await reader.readline()
                if not data:
                    break
                
                # Parse JSON message
                try:
                    message = json.loads(data.decode('utf-8').strip())
                    msg_type = message.get('type', '')
                    
                    logger.debug(f"Received from uid={uid}: {msg_type}")
                    
                    # Dispatch message to appropriate handler
                    if msg_type == MessageTypes.LOGIN:
                        await self.chat_server.handle_login(uid, message, self.clients)
                    elif msg_type == MessageTypes.HEARTBEAT:
                        await self.chat_server.handle_heartbeat(uid, message, self.clients)
                    elif msg_type == MessageTypes.CHAT:
                        await self.chat_server.handle_chat(uid, message, self.clients)
                    elif msg_type == MessageTypes.BROADCAST:
                        await self.chat_server.handle_broadcast(uid, message, self.clients)
                    elif msg_type == MessageTypes.UNICAST:
                        await self.chat_server.handle_unicast(uid, message, self.clients)
                    elif msg_type == MessageTypes.GET_HISTORY:
                        await self.chat_server.handle_get_history(uid, message, self.clients)
                    elif msg_type == MessageTypes.FILE_OFFER:
                        await self.file_server.handle_file_offer(uid, message, self.clients, self.config.host)
                    elif msg_type == MessageTypes.FILE_REQUEST:
                        await self.file_server.handle_file_request(uid, message, self.clients, self.config.host)
                    elif msg_type == MessageTypes.PRESENT_START:
                        await self.screen_server.handle_present_start(uid, message, self.clients, self.config.host)
                    elif msg_type == MessageTypes.PRESENT_STOP:
                        await self.screen_server.handle_present_stop(uid, message, self.clients)
                    elif msg_type == MessageTypes.LOGOUT:
                        await self.chat_server.handle_logout(uid, message, self.clients)
                        break
                    else:
                        logger.warning(f"Unknown message type '{msg_type}' from uid={uid}")
                
                except json.JSONDecodeError as e:
                    logger.error(f"Malformed JSON from uid={uid}: {e}")
                    # Send error message back to client
                    await self.send_message(uid, {
                        "type": "error",
                        "message": "Malformed JSON"
                    })
                except Exception as e:
                    logger.error(f"Error processing message from uid={uid}: {e}")
        
        except asyncio.CancelledError:
            logger.info(f"Connection cancelled for uid={uid}")
        except Exception as e:
            logger.error(f"Socket error for uid={uid}: {e}")
        finally:
            await self.disconnect_client(uid)
    
    async def start(self):
        """Start the server."""
        server = await asyncio.start_server(
            self.handle_client,
            self.config.host,
            self.config.port
        )
        
        addr = ', '.join(str(sock.getsockname()) for sock in server.sockets)
        logger.info(f"Server listening on {addr}")
        
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    try:
        server = CollaborationServer(host='0.0.0.0', port=9000)
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
    except Exception as e:
        logger.log_error("server", e)
