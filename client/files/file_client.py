"""
File client module.

This module handles client-side file transfer functionality.
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional, Callable

from common.constants import MessageTypes, CHUNK_SIZE, PROGRESS_LOG_INTERVAL
from common.protocol_definitions import create_file_offer_message, create_file_request_message


class FileClient:
    """Client-side file transfer functionality."""
    
    def __init__(self, writer: Optional[asyncio.StreamWriter] = None):
        self.writer = writer
        self.host = 'localhost'
        self.pending_uploads = {}  # fid -> file_path
        self.pending_downloads = {}  # fid -> save_path
        self.message_handler: Optional[Callable] = None
    
    def set_writer(self, writer: asyncio.StreamWriter):
        """Set the writer for sending messages."""
        self.writer = writer
    
    def set_host(self, host: str):
        """Set the server host for file transfers."""
        self.host = host
    
    def set_message_handler(self, handler: Callable):
        """Set the message handler for incoming messages."""
        self.message_handler = handler
    
    async def send_message(self, message: dict) -> bool:
        """Send a JSON message to the server."""
        if not self.writer:
            print("[ERROR] Not connected to server")
            return False
        
        try:
            import json
            msg_data = json.dumps(message).encode('utf-8') + b'\n'
            self.writer.write(msg_data)
            await self.writer.drain()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")
            return False
    
    async def upload_file(self, file_path: str) -> Optional[str]:
        """Upload a file to the server."""
        path = Path(file_path)
        
        if not path.exists():
            print(f"[ERROR] File not found: {file_path}")
            return None
        
        if not path.is_file():
            print(f"[ERROR] Not a file: {file_path}")
            return None
        
        # Generate unique file ID
        fid = str(uuid.uuid4())
        filename = path.name
        size = path.stat().st_size
        
        print(f"[UPLOAD] Offering file: {filename} ({size} bytes, fid={fid})")
        
        # Store pending upload
        self.pending_uploads[fid] = str(path.absolute())
        
        # Send file offer
        offer_msg = create_file_offer_message(fid, filename, size)
        await self.send_message(offer_msg)
        
        return fid
    
    async def do_file_upload(self, fid: str, file_path: str, upload_port: int) -> bool:
        """Perform the actual file upload to the given port."""
        path = Path(file_path)
        
        if not path.exists():
            print(f"[ERROR] File disappeared: {file_path}")
            return False
        
        try:
            print(f"[UPLOAD] Connecting to upload port {upload_port}...")
            reader, writer = await asyncio.open_connection(self.host, upload_port)
            
            size = path.stat().st_size
            bytes_sent = 0
            
            print(f"[UPLOAD] Uploading {path.name}...")
            
            with open(path, 'rb') as f:
                while True:
                    data = f.read(CHUNK_SIZE)
                    if not data:
                        break
                    
                    writer.write(data)
                    await writer.drain()
                    bytes_sent += len(data)
                    
                    # Show progress every 1MB
                    if bytes_sent % PROGRESS_LOG_INTERVAL < CHUNK_SIZE or bytes_sent == size:
                        progress = (bytes_sent / size) * 100
                        print(f"[UPLOAD] Progress: {bytes_sent}/{size} bytes ({progress:.1f}%)")
            
            writer.close()
            await writer.wait_closed()
            
            print(f"[UPLOAD] Upload complete: {path.name}")
            return True
        
        except Exception as e:
            print(f"[ERROR] Upload failed: {e}")
            return False
    
    async def download_file(self, fid: str, save_path: str = None) -> bool:
        """Download a file from the server."""
        print(f"[DOWNLOAD] Requesting file with fid={fid}")
        
        # Send file request
        request_msg = create_file_request_message(fid)
        await self.send_message(request_msg)
        
        # Store download info for when we receive the port
        if save_path:
            self.pending_downloads[fid] = save_path
        
        return True
    
    async def do_file_download(self, fid: str, filename: str, size: int, download_port: int, save_path: str = None) -> bool:
        """Perform the actual file download from the given port."""
        if save_path is None:
            # Default: save to downloads directory
            save_path = os.path.join("downloads", filename)
        
        # Ensure downloads directory exists
        save_dir = Path(save_path).parent
        save_dir.mkdir(parents=True, exist_ok=True)
        print(f"[DOWNLOAD] Saving to: {save_path}")
        
        try:
            print(f"[DOWNLOAD] Connecting to download port {download_port}...")
            reader, writer = await asyncio.open_connection(self.host, download_port)
            
            bytes_received = 0
            
            print(f"[DOWNLOAD] Downloading {filename}...")
            
            with open(save_path, 'wb') as f:
                while bytes_received < size:
                    data = await reader.read(CHUNK_SIZE)
                    if not data:
                        break
                    
                    f.write(data)
                    bytes_received += len(data)
                    
                    # Show progress every 1MB
                    if bytes_received % PROGRESS_LOG_INTERVAL < CHUNK_SIZE or bytes_received == size:
                        progress = (bytes_received / size) * 100
                        print(f"[DOWNLOAD] Progress: {bytes_received}/{size} bytes ({progress:.1f}%)")
            
            writer.close()
            await writer.wait_closed()
            
            if bytes_received == size:
                print(f"[DOWNLOAD] Download complete: {save_path}")
                return True
            else:
                print(f"[ERROR] Incomplete download: {bytes_received}/{size} bytes")
                # Clean up incomplete file
                Path(save_path).unlink(missing_ok=True)
                return False
        
        except Exception as e:
            print(f"[ERROR] Download failed: {e}")
            Path(save_path).unlink(missing_ok=True)
            return False
    
    async def handle_message(self, message: dict):
        """Handle different types of file messages from server."""
        msg_type = message.get('type', '')
        
        if msg_type == MessageTypes.FILE_UPLOAD_PORT:
            await self._handle_file_upload_port(message)
        elif msg_type == MessageTypes.FILE_DOWNLOAD_PORT:
            await self._handle_file_download_port(message)
        elif msg_type == MessageTypes.FILE_AVAILABLE:
            await self._handle_file_available(message)
    
    async def _handle_file_upload_port(self, message: dict):
        """Handle file upload port response."""
        fid = message.get('fid')
        port = message.get('port')
        print(f"[UPLOAD] Received upload port {port} for fid={fid}")
        
        # Get the pending upload file path
        file_path = self.pending_uploads.get(fid)
        if file_path:
            # Start upload in background
            asyncio.create_task(self.do_file_upload(fid, file_path, port))
            # Remove from pending after starting
            del self.pending_uploads[fid]
        else:
            print(f"[ERROR] No pending upload for fid={fid}")
    
    async def _handle_file_download_port(self, message: dict):
        """Handle file download port response."""
        fid = message.get('fid')
        filename = message.get('filename')
        size = message.get('size')
        port = message.get('port')
        print(f"[DOWNLOAD] Received download port {port} for {filename}")
        
        # Get the save path if specified
        save_path = self.pending_downloads.get(fid)
        
        # Start download in background
        asyncio.create_task(self.do_file_download(fid, filename, size, port, save_path))
        
        # Remove from pending after starting
        if fid in self.pending_downloads:
            del self.pending_downloads[fid]
    
    async def _handle_file_available(self, message: dict):
        """Handle file available notification."""
        fid = message.get('fid')
        filename = message.get('filename')
        size = message.get('size')
        uploader = message.get('uploader')
        print(f"[FILE] Available: {filename} ({size} bytes) from {uploader} [fid={fid}]")
