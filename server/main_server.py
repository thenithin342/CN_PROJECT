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

# Try to import audio server, make it optional
try:
    from server.audio.audio_server import AudioServer
    HAS_AUDIO = True
except Exception as e:
    logger.warning(f"Audio server not available: {e}")
    HAS_AUDIO = False
    AudioServer = None

# Try to import video server, make it optional
try:
    from server.video.video_server import VideoServer
    HAS_VIDEO = True
except Exception as e:
    logger.warning(f"Video server not available: {e}")
    HAS_VIDEO = False
    VideoServer = None


class CollaborationServer:
    """Main server class that integrates all functionality."""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 9000, upload_dir: str = 'uploads', 
                 audio_port: int = 11000, video_port: int = 10000):
        self.config = ServerConfig(host, port, upload_dir)
        self.clients: Dict[int, asyncio.StreamWriter] = {}  # uid -> writer
        
        # Initialize modules
        self.chat_server = ChatServer()
        self.file_server = FileServer(upload_dir, self.chat_server.participants, self.broadcast)
        self.screen_server = ScreenServer(self.chat_server.participants)
        
        # Initialize audio server if available
        self.audio_server = None
        self.audio_task = None
        if HAS_AUDIO and AudioServer:
            try:
                self.audio_server = AudioServer(host, audio_port)
                logger.info("Audio server initialized")
            except Exception as e:
                logger.warning(f"Could not initialize audio server: {e}")
                self.audio_server = None
        else:
            logger.info("Audio server not available (opuslib not installed)")
        
        # Initialize video server if available
        self.video_server = None
        self.video_task = None
        if HAS_VIDEO and VideoServer:
            try:
                self.video_server = VideoServer(host, video_port)
                logger.info("Video server initialized")
            except Exception as e:
                logger.warning(f"Could not initialize video server: {e}")
                self.video_server = None
        else:
            logger.info("Video server not available (opencv-python not installed)")
    
    async def broadcast(self, message: dict, exclude_uid: int = None):
        """Send a JSON message to all connected clients."""
        logger.info(f"[BROADCAST] Broadcasting message type={message.get('type')} to {len(self.clients)} clients, exclude_uid={exclude_uid}")
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
        
        # Validate UID is within reasonable range BEFORE adding to clients
        if not isinstance(uid, int) or uid < 0 or uid > 0x7FFFFFFF:
            logger.error(f"[ERROR] Invalid UID assigned: {uid}")
            writer.close()
            await writer.wait_closed()
            return
        
        # Only add to clients after validation passes
        self.clients[uid] = writer
        
        logger.log_connection(addr, uid)
        
        try:
            while True:
                # Read line-delimited JSON
                data = await reader.readline()
                if not data:
                    break
                
                # Validate message size BEFORE parsing (limit to 1MB for safety)
                if len(data) > 1024 * 1024:
                    logger.warning(f"Message too large from uid={uid}: {len(data)} bytes")
                    await self.send_message(uid, {
                        "type": "error",
                        "message": "Message too large"
                    })
                    continue
                
                # Parse JSON message
                try:
                    message = json.loads(data.decode('utf-8').strip())
                    msg_type = message.get('type', '')
                    
                    # Validate message type
                    if not isinstance(msg_type, str) or len(msg_type) == 0:
                        logger.warning(f"Received message with invalid type from uid={uid}")
                        continue
                    
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
        # Helper function to log task exceptions
        def done_callback(name):
            def callback(task):
                if task.exception():
                    logger.error(f"{name} task failed with exception: {task.exception()}")
            return callback
        
        # Start audio server in background if available
        if self.audio_server:
            try:
                self.audio_task = asyncio.create_task(self.audio_server.start())
                self.audio_task.add_done_callback(done_callback("Audio server"))
                logger.info("Audio server started")
            except Exception as e:
                logger.warning(f"Could not start audio server: {e}")
        
        # Start video server in background if available
        if self.video_server:
            try:
                self.video_task = asyncio.create_task(self.video_server.start())
                self.video_task.add_done_callback(done_callback("Video server"))
                logger.info("Video server started")
            except Exception as e:
                logger.warning(f"Could not start video server: {e}")
        
        # Start main TCP server
        server = await asyncio.start_server(
            self.handle_client,
            self.config.host,
            self.config.port
        )
        
        addr = ', '.join(str(sock.getsockname()) for sock in server.sockets)
        logger.info(f"Server listening on {addr}")
        
        async with server:
            await server.serve_forever()


import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='LAN Collaboration Server')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=9000,
                       help='TCP port for main server (default: 9000)')
    parser.add_argument('--audio-port', type=int, default=11000,
                       help='UDP port for audio server (default: 11000)')
    parser.add_argument('--video-port', type=int, default=10000,
                       help='UDP port for video server (default: 10000)')
    parser.add_argument('--upload-dir', type=str, default='uploads',
                       help='Directory for file uploads (default: uploads)')

    args = parser.parse_args()

    server = None
    try:
        server = CollaborationServer(
            host=args.host,
            port=args.port,
            audio_port=args.audio_port,
            video_port=args.video_port,
            upload_dir=args.upload_dir
        )
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
        if server and hasattr(server, 'audio_server') and server.audio_server:
            server.audio_server.stop()
        if server and hasattr(server, 'video_server') and server.video_server:
            server.video_server.stop()
    except Exception as e:
        logger.log_error("server", e)
        if server and hasattr(server, 'audio_server') and server.audio_server:
            server.audio_server.stop()
        if server and hasattr(server, 'video_server') and server.video_server:
            server.video_server.stop()
