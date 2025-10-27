"""
Screen server module.

This module handles server-side screen sharing functionality.
"""

import asyncio
import struct
from datetime import datetime
from typing import Dict, Optional

from common.constants import MessageTypes
from common.protocol_definitions import (
    create_screen_share_ports_message, create_present_start_broadcast_message,
    create_present_stop_broadcast_message, create_error_message
)
from server.utils.logger import logger


class ScreenServer:
    """Server-side screen sharing functionality."""
    
    def __init__(self, participants: dict = None):
        self.presentation_active = False
        self.presenter_uid = None
        self.presenter_username = None
        self.presenter_port = None  # Port for presenter to send frames
        self.viewer_port = None  # Port for viewers to receive frames
        self.presenter_writer = None  # Presenter connection
        self.viewers: Dict[int, asyncio.StreamWriter] = {}  # uid -> viewer writer
        self.frame_relay_task = None
        self.next_ephemeral_port = 11001  # Changed from 10000 to avoid conflict with video server
        self.lock = asyncio.Lock()  # Protect shared state
        self.participants = participants or {}  # Reference to participants dict
    
    def get_ephemeral_port(self) -> int:
        """Allocate an ephemeral port for screen sharing."""
        port = self.next_ephemeral_port
        self.next_ephemeral_port += 1
        return port
    
    async def handle_present_start(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter], host: str):
        """Start screen sharing presentation."""
        username = self._get_username(uid)
        topic = data.get('topic', 'Screen Share')
        
        # Check if presentation already active
        if self.presentation_active:
            logger.warning(f"Presentation already active by {self.presenter_username}")
            await self._send_message(uid, create_error_message(f"Presentation already active by {self.presenter_username}"), clients)
            return
        
        logger.log_screen_share_start(username, uid, topic, 0, 0)  # Ports will be updated
        
        # Allocate ports
        self.presenter_port = self.get_ephemeral_port()
        self.viewer_port = self.get_ephemeral_port()
        
        # Set presentation state
        self.presentation_active = True
        self.presenter_uid = uid
        self.presenter_username = username
        
        logger.info(f"  Presenter port: {self.presenter_port}")
        logger.info(f"  Viewer port: {self.viewer_port}")
        
        # Log screen share start
        logger.log_screen_share_start(username, uid, topic, self.presenter_port, self.viewer_port)
        
        # Start presenter server
        async def accept_presenter(reader, writer):
            self.presenter_writer = writer
            addr = writer.get_extra_info('peername')
            logger.info(f"[SCREEN SHARE] Presenter connected from {addr}")
            
            # Start frame relay
            self.frame_relay_task = asyncio.create_task(self.relay_frames(reader))
        
        try:
            presenter_server = await asyncio.start_server(
                accept_presenter, host, self.presenter_port
            )
            logger.info(f"[SCREEN SHARE] Presenter server started on port {self.presenter_port}")
            
            # Start viewer server
            async def accept_viewer(reader, writer):
                # Viewers are stored and frames are relayed to them
                viewer_addr = writer.get_extra_info('peername')
                logger.info(f"[SCREEN SHARE] Viewer connected from {viewer_addr}")
                
                # Log viewer connection
                logger.log_viewer_join(self.presenter_username, self.presenter_uid, viewer_addr)
                
                async with self.lock:
                    # Use a unique ID for this viewer connection
                    viewer_id = id(writer)
                    self.viewers[viewer_id] = writer
            
            viewer_server = await asyncio.start_server(
                accept_viewer, host, self.viewer_port
            )
            logger.info(f"[SCREEN SHARE] Viewer server started on port {self.viewer_port}")
            
            # Reply to presenter with ports
            await self._send_message(uid, create_screen_share_ports_message(self.presenter_port, self.viewer_port), clients)
            
            # Broadcast to all clients
            await self._broadcast(create_present_start_broadcast_message(uid, username, topic, self.viewer_port), clients)
            
            logger.info(f"[SCREEN SHARE] Broadcast sent to all clients")
        
        except Exception as e:
            logger.error(f"Failed to start screen sharing: {e}")
            self.presentation_active = False
            self.presenter_uid = None
            self.presenter_username = None
            await self._send_message(uid, create_error_message(f"Failed to start screen sharing: {e}"), clients)
    
    async def handle_present_stop(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Stop screen sharing presentation."""
        username = self._get_username(uid)
        
        if not self.presentation_active:
            logger.warning(f"No active presentation to stop")
            return
        
        if uid != self.presenter_uid:
            logger.warning(f"{username} tried to stop presentation by {self.presenter_username}")
            await self._send_message(uid, create_error_message("You are not the presenter"), clients)
            return
        
        logger.log_screen_share_stop(username, uid, len(self.viewers))
        
        # Stop frame relay
        if self.frame_relay_task:
            self.frame_relay_task.cancel()
            try:
                await self.frame_relay_task
            except asyncio.CancelledError:
                pass
        
        # Close presenter connection
        if self.presenter_writer:
            try:
                self.presenter_writer.close()
                await self.presenter_writer.wait_closed()
            except Exception:
                pass
        
        # Close all viewer connections
        async with self.lock:
            for viewer_writer in self.viewers.values():
                try:
                    viewer_writer.close()
                    await viewer_writer.wait_closed()
                except Exception:
                    pass
            self.viewers.clear()
        
        # Reset state
        self.presentation_active = False
        self.presenter_uid = None
        self.presenter_username = None
        self.presenter_port = None
        self.viewer_port = None
        
        # Broadcast stop to all clients
        await self._broadcast(create_present_stop_broadcast_message(uid, username), clients)
    
    async def relay_frames(self, presenter_reader: asyncio.StreamReader):
        """Relay frames from presenter to all viewers."""
        logger.info("[SCREEN SHARE] Starting frame relay")
        
        try:
            while self.presentation_active:
                # Read frame from presenter
                try:
                    # Read 4-byte frame length header
                    length_data = await presenter_reader.readexactly(4)
                    frame_length = struct.unpack('!I', length_data)[0]
                    
                    # Read frame data
                    frame_data = await presenter_reader.readexactly(frame_length)
                    
                    # Relay to all viewers
                    disconnected_viewers = []
                    async with self.lock:
                        for viewer_uid, viewer_writer in self.viewers.items():
                            try:
                                viewer_writer.write(length_data + frame_data)
                                await viewer_writer.drain()
                            except Exception as e:
                                logger.error(f"Failed to relay to viewer uid={viewer_uid}: {e}")
                                disconnected_viewers.append(viewer_uid)
                    
                    # Clean up disconnected viewers
                    for viewer_uid in disconnected_viewers:
                        async with self.lock:
                            if viewer_uid in self.viewers:
                                del self.viewers[viewer_uid]
                
                except asyncio.IncompleteReadError:
                    logger.info("[SCREEN SHARE] Presenter disconnected")
                    break
                except Exception as e:
                    logger.error(f"[SCREEN SHARE] Frame relay error: {e}")
                    break
        
        finally:
            logger.info("[SCREEN SHARE] Frame relay stopped")
    
    async def _send_message(self, uid: int, message: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Send a JSON message to a specific client."""
        async with self.lock:
            writer = clients.get(uid)
            if writer:
                try:
                    import json
                    msg_data = json.dumps(message).encode('utf-8') + b'\n'
                    writer.write(msg_data)
                    await writer.drain()
                except Exception as e:
                    logger.error(f"Failed to send to uid={uid}: {e}")
                    return False
        return True
    
    async def _broadcast(self, message: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Broadcast message to all clients."""
        import json
        msg_data = json.dumps(message).encode('utf-8') + b'\n'
        disconnected = []
        
        async with self.lock:
            for uid, writer in clients.items():
                try:
                    writer.write(msg_data)
                    await writer.drain()
                except Exception as e:
                    logger.error(f"Failed to broadcast to uid={uid}: {e}")
                    disconnected.append(uid)
        
        return disconnected
    
    def _get_username(self, uid: int) -> str:
        """Get username for a UID."""
        return self.participants.get(uid, {}).get('username', f'user_{uid}')
