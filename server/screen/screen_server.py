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
        self.presentations = {}  # uid -> presentation info
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

        # Check if user already has an active presentation
        if uid in self.presentations:
            logger.warning(f"User {username} already has an active presentation")
            await self._send_message(uid, create_error_message("You already have an active presentation"), clients)
            return

        logger.log_screen_share_start(username, uid, topic, 0, 0)  # Ports will be updated

        # Allocate ports for this presentation
        presenter_port = self.get_ephemeral_port()
        viewer_port = self.get_ephemeral_port()

        # Create presentation info
        presentation = {
            'username': username,
            'topic': topic,
            'presenter_port': presenter_port,
            'viewer_port': viewer_port,
            'presenter_writer': None,
            'viewers': {},  # viewer_id -> writer
            'frame_relay_task': None,
            'presenter_server': None,
            'viewer_server': None
        }

        self.presentations[uid] = presentation

        logger.info(f"  Presenter port: {presenter_port}")
        logger.info(f"  Viewer port: {viewer_port}")

        # Log screen share start
        logger.log_screen_share_start(username, uid, topic, presenter_port, viewer_port)

        # Start presenter server
        async def accept_presenter(reader, writer):
            presentation['presenter_writer'] = writer
            addr = writer.get_extra_info('peername')
            logger.info(f"[SCREEN SHARE] Presenter {username} connected from {addr}")

            # Start frame relay for this presentation
            presentation['frame_relay_task'] = asyncio.create_task(self.relay_frames_for_presentation(uid, reader))

        try:
            presentation['presenter_server'] = await asyncio.start_server(
                accept_presenter, host, presenter_port
            )
            logger.info(f"[SCREEN SHARE] Presenter server for {username} started on port {presenter_port}")

            # Start viewer server
            async def accept_viewer(reader, writer):
                # Viewers are stored and frames are relayed to them
                viewer_addr = writer.get_extra_info('peername')
                logger.info(f"[SCREEN SHARE] Viewer connected to {username}'s presentation from {viewer_addr}")

                # Log viewer connection
                logger.log_viewer_join(username, uid, viewer_addr)

                async with self.lock:
                    # Use a unique ID for this viewer connection
                    viewer_id = id(writer)
                    presentation['viewers'][viewer_id] = writer

            presentation['viewer_server'] = await asyncio.start_server(
                accept_viewer, host, viewer_port
            )
            logger.info(f"[SCREEN SHARE] Viewer server for {username} started on port {viewer_port}")

            # Reply to presenter with ports
            await self._send_message(uid, create_screen_share_ports_message(presenter_port, viewer_port), clients)

            # Broadcast to all clients
            await self._broadcast(create_present_start_broadcast_message(uid, username, topic, viewer_port), clients)

            logger.info(f"[SCREEN SHARE] Broadcast sent to all clients for {username}'s presentation")

        except Exception as e:
            logger.error(f"Failed to start screen sharing for {username}: {e}")
            # Clean up on failure
            await self._cleanup_presentation(uid)
            await self._send_message(uid, create_error_message(f"Failed to start screen sharing: {e}"), clients)
    
    async def handle_present_stop(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Stop screen sharing presentation."""
        username = self._get_username(uid)

        if uid not in self.presentations:
            logger.warning(f"No active presentation for {username}")
            await self._send_message(uid, create_error_message("You don't have an active presentation"), clients)
            return

        presentation = self.presentations[uid]
        logger.log_screen_share_stop(username, uid, len(presentation['viewers']))

        # Clean up the presentation
        await self._cleanup_presentation(uid)

        # Broadcast stop to all clients
        await self._broadcast(create_present_stop_broadcast_message(uid, username), clients)
    
    async def relay_frames_for_presentation(self, presenter_uid: int, presenter_reader: asyncio.StreamReader):
        """Relay frames from presenter to all viewers for a specific presentation."""
        presentation = self.presentations.get(presenter_uid)
        if not presentation:
            logger.error(f"No presentation found for uid {presenter_uid}")
            return

        username = presentation['username']
        logger.info(f"[SCREEN SHARE] Starting frame relay for {username}'s presentation")

        try:
            while presenter_uid in self.presentations:
                # Read frame from presenter
                try:
                    # Read 4-byte frame length header
                    length_data = await presenter_reader.readexactly(4)
                    frame_length = struct.unpack('!I', length_data)[0]

                    # Read frame data
                    frame_data = await presenter_reader.readexactly(frame_length)

                    # Relay to all viewers of this presentation
                    disconnected_viewers = []
                    async with self.lock:
                        for viewer_id, viewer_writer in presentation['viewers'].items():
                            try:
                                viewer_writer.write(length_data + frame_data)
                                await viewer_writer.drain()
                            except Exception as e:
                                logger.error(f"Failed to relay to viewer {viewer_id} for {username}: {e}")
                                disconnected_viewers.append(viewer_id)

                    # Clean up disconnected viewers
                    for viewer_id in disconnected_viewers:
                        async with self.lock:
                            if viewer_id in presentation['viewers']:
                                del presentation['viewers'][viewer_id]

                except asyncio.IncompleteReadError:
                    logger.info(f"[SCREEN SHARE] Presenter {username} disconnected")
                    break
                except Exception as e:
                    logger.error(f"[SCREEN SHARE] Frame relay error for {username}: {e}")
                    break

        finally:
            logger.info(f"[SCREEN SHARE] Frame relay stopped for {username}'s presentation")
            # Clean up the presentation when relay stops
            await self._cleanup_presentation(presenter_uid)
    
    async def _cleanup_presentation(self, uid: int):
        """Clean up a presentation and its resources."""
        if uid not in self.presentations:
            return

        presentation = self.presentations[uid]
        username = presentation['username']

        logger.info(f"[SCREEN SHARE] Cleaning up presentation for {username}")

        # Stop frame relay
        if presentation['frame_relay_task']:
            presentation['frame_relay_task'].cancel()
            try:
                await presentation['frame_relay_task']
            except asyncio.CancelledError:
                pass

        # Close presenter connection
        if presentation['presenter_writer']:
            try:
                presentation['presenter_writer'].close()
                await presentation['presenter_writer'].wait_closed()
            except Exception:
                pass

        # Close all viewer connections
        async with self.lock:
            for viewer_writer in presentation['viewers'].values():
                try:
                    viewer_writer.close()
                    await viewer_writer.wait_closed()
                except Exception:
                    pass

        # Close servers
        if presentation['presenter_server']:
            presentation['presenter_server'].close()
            await presentation['presenter_server'].wait_closed()

        if presentation['viewer_server']:
            presentation['viewer_server'].close()
            await presentation['viewer_server'].wait_closed()

        # Remove from presentations
        del self.presentations[uid]
        logger.info(f"[SCREEN SHARE] Presentation cleanup complete for {username}")

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
