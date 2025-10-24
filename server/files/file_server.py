"""
File server module.

This module handles server-side file transfer functionality.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from common.constants import MessageTypes, CHUNK_SIZE, PROGRESS_LOG_INTERVAL, TRANSFER_TIMEOUT
from common.protocol_definitions import (
    create_file_upload_port_message, create_file_download_port_message,
    create_file_available_message, create_error_message
)
from server.utils.logger import logger


class FileServer:
    """Server-side file transfer functionality."""
    
    def __init__(self, upload_dir: str = 'uploads', participants: dict = None, broadcast_callback=None):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(exist_ok=True)  # Create uploads directory
        self.files: Dict[str, dict] = {}  # fid -> file metadata
        self.upload_sessions: Dict[int, dict] = {}  # port -> session info
        self.download_sessions: Dict[int, dict] = {}  # port -> session info
        self.next_ephemeral_port = 10000  # Start ephemeral ports from 10000
        self.lock = asyncio.Lock()  # Protect shared state
        self.participants = participants or {}  # Reference to participants dict
        self.broadcast_callback = broadcast_callback  # Callback for broadcasting messages
    
    def get_ephemeral_port(self) -> int:
        """Allocate an ephemeral port for file transfer."""
        port = self.next_ephemeral_port
        self.next_ephemeral_port += 1
        return port
    
    async def handle_file_offer(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter], host: str):
        """Process file offer and set up upload port."""
        filename = data.get('filename', '')
        size = data.get('size', 0)
        fid = data.get('fid', '')
        username = self._get_username(uid)
        
        if not fid or not filename or size <= 0:
            logger.error(f"Invalid file offer from uid={uid}: missing fid/filename/size")
            await self._send_message(uid, create_error_message("Invalid file offer: missing fid, filename, or size"), clients)
            return
        
        logger.info(f"File offer from {username} (uid={uid}): {filename} ({size} bytes, fid={fid})")
        
        # Allocate ephemeral port for upload
        upload_port = self.get_ephemeral_port()
        
        # Store session info
        session_info = {
            'fid': fid,
            'filename': filename,
            'size': size,
            'uploader': username,
            'uid': uid,
            'port': upload_port
        }
        
        async with self.lock:
            self.upload_sessions[upload_port] = session_info
        
        # Start upload server on ephemeral port
        async def accept_upload(reader, writer):
            await self.handle_file_upload(reader, writer, session_info)
            # Clean up session after upload
            async with self.lock:
                if upload_port in self.upload_sessions:
                    del self.upload_sessions[upload_port]
        
        try:
            upload_server = await asyncio.start_server(accept_upload, host, upload_port)
            logger.info(f"Upload server started on port {upload_port} for fid={fid}")
            
            # Reply to client with upload port
            await self._send_message(uid, create_file_upload_port_message(fid, upload_port), clients)
            
            # Schedule server cleanup after upload timeout
            async def cleanup_server():
                await asyncio.sleep(TRANSFER_TIMEOUT)  # 5 minute timeout
                upload_server.close()
                await upload_server.wait_closed()
                async with self.lock:
                    if upload_port in self.upload_sessions:
                        del self.upload_sessions[upload_port]
                logger.info(f"Upload server on port {upload_port} timed out and closed")
            
            asyncio.create_task(cleanup_server())
        
        except Exception as e:
            logger.error(f"Failed to start upload server on port {upload_port}: {e}")
            await self._send_message(uid, create_error_message(f"Failed to start upload server: {e}"), clients)
            async with self.lock:
                if upload_port in self.upload_sessions:
                    del self.upload_sessions[upload_port]
    
    async def handle_file_request(self, uid: int, data: dict, clients: Dict[int, asyncio.StreamWriter], host: str):
        """Process file download request and set up download port."""
        fid = data.get('fid', '')
        username = self._get_username(uid)
        
        if not fid:
            logger.error(f"Invalid file request from uid={uid}: missing fid")
            await self._send_message(uid, create_error_message("Invalid file request: missing fid"), clients)
            return
        
        # Check if file exists
        async with self.lock:
            file_info = self.files.get(fid)
        
        if not file_info:
            logger.warning(f"File request from {username} (uid={uid}) for unknown fid={fid}")
            await self._send_message(uid, create_error_message(f"File not found: fid={fid}"), clients)
            return
        
        uploader = file_info['uploader']
        filename = file_info['filename']
        
        logger.log_file_request(filename, username, uploader, fid)
        
        # Allocate ephemeral port for download
        download_port = self.get_ephemeral_port()
        
        # Store session info
        session_info = {
            'fid': fid,
            'filename': file_info['filename'],
            'size': file_info['size'],
            'requester': username,
            'uid': uid,
            'port': download_port
        }
        
        async with self.lock:
            self.download_sessions[download_port] = session_info
        
        # Start download server on ephemeral port
        async def accept_download(reader, writer):
            await self.handle_file_download(reader, writer, session_info)
            # Clean up session after download
            async with self.lock:
                if download_port in self.download_sessions:
                    del self.download_sessions[download_port]
        
        try:
            download_server = await asyncio.start_server(accept_download, host, download_port)
            logger.info(f"Download server started on port {download_port} for fid={fid}")
            
            # Reply to client with download port
            await self._send_message(uid, create_file_download_port_message(fid, file_info['filename'], file_info['size'], download_port), clients)
            
            # Schedule server cleanup after download timeout
            async def cleanup_server():
                await asyncio.sleep(TRANSFER_TIMEOUT)  # 5 minute timeout
                download_server.close()
                await download_server.wait_closed()
                async with self.lock:
                    if download_port in self.download_sessions:
                        del self.download_sessions[download_port]
                logger.info(f"Download server on port {download_port} timed out and closed")
            
            asyncio.create_task(cleanup_server())
        
        except Exception as e:
            logger.error(f"Failed to start download server on port {download_port}: {e}")
            await self._send_message(uid, create_error_message(f"Failed to start download server: {e}"), clients)
            async with self.lock:
                if download_port in self.download_sessions:
                    del self.download_sessions[download_port]
    
    async def handle_file_upload(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, session_info: dict):
        """Handle file upload on ephemeral port."""
        fid = session_info['fid']
        filename = session_info['filename']
        expected_size = session_info['size']
        uploader = session_info['uploader']
        uid = session_info['uid']
        
        addr = writer.get_extra_info('peername')
        logger.info(f"File upload connection from {addr} for fid={fid}")
        
        file_path = self.upload_dir / filename
        bytes_received = 0
        
        try:
            with open(file_path, 'wb') as f:
                while bytes_received < expected_size:
                    # Read in chunks
                    chunk_size = min(CHUNK_SIZE, expected_size - bytes_received)
                    data = await reader.read(chunk_size)
                    
                    if not data:
                        logger.warning(f"Connection closed before upload complete: {bytes_received}/{expected_size} bytes")
                        break
                    
                    f.write(data)
                    bytes_received += len(data)
                    
                    # Log progress every 1MB
                    if bytes_received % PROGRESS_LOG_INTERVAL < CHUNK_SIZE:
                        progress = (bytes_received / expected_size) * 100
                        logger.info(f"Upload progress [{fid}]: {bytes_received}/{expected_size} bytes ({progress:.1f}%)")
            
            if bytes_received == expected_size:
                logger.log_file_upload(filename, bytes_received, uploader, fid)
                
                # Store file metadata
                file_metadata = {
                    'fid': fid,
                    'filename': filename,
                    'size': bytes_received,
                    'uploader': uploader,
                    'uploader_uid': uid,
                    'path': str(file_path),
                    'uploaded_at': datetime.now().isoformat()
                }
                
                async with self.lock:
                    self.files[fid] = file_metadata
                
                # Store for broadcasting
                self.last_uploaded_file = file_metadata
                
                # Broadcast file availability
                if self.broadcast_callback:
                    await self.broadcast_callback(create_file_available_message(fid, filename, bytes_received, uploader))
                logger.info(f"  Broadcast sent to all clients")
            else:
                logger.error(f"Upload incomplete: {bytes_received}/{expected_size} bytes")
                # Clean up incomplete file
                if file_path.exists():
                    file_path.unlink()
        
        except Exception as e:
            logger.error(f"Error during file upload: {e}")
            if file_path.exists():
                file_path.unlink()
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def handle_file_download(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, session_info: dict):
        """Handle file download on ephemeral port."""
        fid = session_info['fid']
        requester = session_info['requester']
        requester_uid = session_info['uid']
        
        addr = writer.get_extra_info('peername')
        logger.info(f"File download connection from {addr} for fid={fid}")
        
        async with self.lock:
            file_info = self.files.get(fid)
        
        if not file_info:
            logger.error(f"File not found for fid={fid}")
            writer.close()
            await writer.wait_closed()
            return
        
        file_path = Path(file_info['path'])
        if not file_path.exists():
            logger.error(f"File missing on disk: {file_path}")
            writer.close()
            await writer.wait_closed()
            return
        
        # Log transfer start
        uploader = file_info['uploader']
        uploader_uid = file_info['uploader_uid']
        filename = file_info['filename']
        
        logger.info(f"⬇ FILE TRANSFER STARTED")
        logger.info(f"  File: '{filename}' (fid={fid[:8]}...)")
        logger.info(f"  From: {uploader} (uid={uploader_uid})")
        logger.info(f"  To: {requester} (uid={requester_uid})")
        
        try:
            bytes_sent = 0
            file_size = file_info['size']
            
            with open(file_path, 'rb') as f:
                while True:
                    data = f.read(CHUNK_SIZE)
                    if not data:
                        break
                    
                    writer.write(data)
                    await writer.drain()
                    bytes_sent += len(data)
                    
                    # Log progress every 1MB
                    if bytes_sent % PROGRESS_LOG_INTERVAL < CHUNK_SIZE:
                        progress = (bytes_sent / file_size) * 100
                        logger.info(f"Download progress [{fid[:8]}...]: {bytes_sent}/{file_size} bytes ({progress:.1f}%)")
            
            logger.log_file_download(filename, bytes_sent, uploader, requester, fid)
        
        except Exception as e:
            logger.error(f"Error during file download: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _send_message(self, uid: int, message: dict, clients: Dict[int, asyncio.StreamWriter]):
        """Send a JSON message to a specific client."""
        async with self.lock:
            writer = clients.get(uid)
            if writer:
                try:
                    msg_data = json.dumps(message).encode('utf-8') + b'\n'
                    writer.write(msg_data)
                    await writer.drain()
                except Exception as e:
                    logger.error(f"Failed to send to uid={uid}: {e}")
                    return False
        return True
    
    def _get_username(self, uid: int) -> str:
        """Get username for a UID."""
        return self.participants.get(uid, {}).get('username', f'user_{uid}')
    
    def broadcast_file_available(self, fid: str, filename: str, size: int, uploader: str, clients: Dict[int, asyncio.StreamWriter]):
        """Broadcast file availability to all clients."""
        # This would need to be called from the main server after successful upload
        # For now, it's a placeholder
        pass
