"""
Screen broadcaster module.

This module handles server-side screen sharing frame broadcasting functionality.
"""

import asyncio
import struct
from typing import Dict, List

from server.utils.logger import logger


class ScreenBroadcaster:
    """Server-side screen sharing frame broadcaster."""
    
    def __init__(self):
        self.viewers: Dict[int, asyncio.StreamWriter] = {}  # uid -> viewer writer
        self.lock = asyncio.Lock()
    
    async def add_viewer(self, viewer_id: int, writer: asyncio.StreamWriter):
        """Add a viewer to the broadcast list."""
        async with self.lock:
            self.viewers[viewer_id] = writer
        logger.info(f"[SCREEN BROADCASTER] Added viewer {viewer_id}")
    
    async def remove_viewer(self, viewer_id: int):
        """Remove a viewer from the broadcast list."""
        async with self.lock:
            if viewer_id in self.viewers:
                writer = self.viewers[viewer_id]
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                del self.viewers[viewer_id]
        logger.info(f"[SCREEN BROADCASTER] Removed viewer {viewer_id}")
    
    async def broadcast_frame(self, frame_data: bytes):
        """Broadcast a frame to all viewers."""
        if not self.viewers:
            return
        
        # Create frame header
        frame_length = len(frame_data)
        header = struct.pack('!I', frame_length)
        full_frame = header + frame_data
        
        disconnected_viewers = []
        
        async with self.lock:
            for viewer_id, writer in self.viewers.items():
                try:
                    writer.write(full_frame)
                    await writer.drain()
                except Exception as e:
                    logger.error(f"[SCREEN BROADCASTER] Failed to send to viewer {viewer_id}: {e}")
                    disconnected_viewers.append(viewer_id)
        
        # Clean up disconnected viewers
        for viewer_id in disconnected_viewers:
            await self.remove_viewer(viewer_id)
    
    async def clear_all_viewers(self):
        """Clear all viewers."""
        async with self.lock:
            for writer in self.viewers.values():
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            self.viewers.clear()
        logger.info("[SCREEN BROADCASTER] Cleared all viewers")
    
    def get_viewer_count(self) -> int:
        """Get the number of current viewers."""
        return len(self.viewers)
