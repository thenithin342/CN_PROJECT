#!/usr/bin/env python3
"""
LAN Multi-User Collaboration Server
Listens on TCP port 9000 and manages multiple client connections.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, Set
from collections import deque
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class CollaborationServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 9000, upload_dir: str = 'uploads'):
        self.host = host
        self.port = port
        self.clients: Dict[int, asyncio.StreamWriter] = {}  # uid -> writer
        self.participants: Dict[int, dict] = {}  # uid -> user info
        self.next_uid = 1
        self.lock = asyncio.Lock()  # Protect shared state
        self.chat_history = deque(maxlen=500)  # Keep last 500 chat messages
        
        # File transfer management
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(exist_ok=True)  # Create uploads directory
        self.files: Dict[str, dict] = {}  # fid -> file metadata
        self.upload_sessions: Dict[int, dict] = {}  # port -> session info
        self.download_sessions: Dict[int, dict] = {}  # port -> session info
        self.next_ephemeral_port = 10000  # Start ephemeral ports from 10000
        
        # Logging paths
        self.logs_dir = Path('logs')
        self.logs_dir.mkdir(exist_ok=True)  # Create logs directory
        self.transfer_log_path = self.logs_dir / 'file_transfers.log'
        self.chat_log_path = self.logs_dir / 'chat_history.log'
        self.screen_share_log_path = self.logs_dir / 'screen_sharing.log'
        
        # Screen sharing management
        self.presentation_active = False
        self.presenter_uid = None
        self.presenter_username = None
        self.presenter_port = None  # Port for presenter to send frames
        self.viewer_port = None  # Port for viewers to receive frames
        self.presenter_writer = None  # Presenter connection
        self.viewers: Dict[int, asyncio.StreamWriter] = {}  # uid -> viewer writer
        self.frame_relay_task = None

    async def broadcast(self, message: dict, exclude_uid: int = None):
        """
        Send a JSON message to all connected clients.
        Optionally exclude a specific client by uid.
        """
        msg_data = json.dumps(message).encode('utf-8') + b'\n'
        disconnected = []
        
        async with self.lock:
            for uid, writer in self.clients.items():
                if exclude_uid is not None and uid == exclude_uid:
                    continue
                try:
                    writer.write(msg_data)
                    await writer.drain()
                except Exception as e:
                    logger.error(f"Failed to broadcast to uid={uid}: {e}")
                    disconnected.append(uid)
        
        # Clean up disconnected clients
        for uid in disconnected:
            await self.disconnect_client(uid)

    async def send_message(self, uid: int, message: dict):
        """Send a JSON message to a specific client."""
        async with self.lock:
            writer = self.clients.get(uid)
            if writer:
                try:
                    msg_data = json.dumps(message).encode('utf-8') + b'\n'
                    writer.write(msg_data)
                    await writer.drain()
                except Exception as e:
                    logger.error(f"Failed to send to uid={uid}: {e}")
                    await self.disconnect_client(uid)

    async def disconnect_client(self, uid: int):
        """Remove client and notify others."""
        async with self.lock:
            if uid in self.clients:
                writer = self.clients[uid]
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                del self.clients[uid]
            
            if uid in self.participants:
                user_info = self.participants[uid]
                del self.participants[uid]
                logger.info(f"User {user_info.get('username', 'unknown')} (uid={uid}) disconnected")
                
                # Broadcast user_left event
                await self.broadcast({
                    "type": "user_left",
                    "uid": uid,
                    "username": user_info.get('username', 'unknown'),
                    "timestamp": datetime.now().isoformat()
                })

    def get_ephemeral_port(self) -> int:
        """Allocate an ephemeral port for file transfer."""
        port = self.next_ephemeral_port
        self.next_ephemeral_port += 1
        return port

    def log_transfer(self, action: str, filename: str, from_user: str, to_user: str = None, 
                    fid: str = None, size: int = 0):
        """Log file transfer to transfer log file."""
        try:
            timestamp = datetime.now().isoformat()
            if to_user:
                log_line = f"{timestamp} | {action} | {filename} | FROM: {from_user} | TO: {to_user} | SIZE: {size} bytes | FID: {fid}\n"
            else:
                log_line = f"{timestamp} | {action} | {filename} | USER: {from_user} | SIZE: {size} bytes | FID: {fid}\n"
            
            with open(self.transfer_log_path, 'a', encoding='utf-8') as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"Failed to write transfer log: {e}")
    
    def log_chat(self, username: str, uid: int, message: str):
        """Log chat message to chat log file."""
        try:
            timestamp = datetime.now().isoformat()
            log_line = f"{timestamp} | {username} (uid={uid}) | {message}\n"
            
            with open(self.chat_log_path, 'a', encoding='utf-8') as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"Failed to write chat log: {e}")
    
    def log_screen_share(self, action: str, username: str, uid: int, details: str = ""):
        """Log screen sharing activity to screen share log file."""
        try:
            timestamp = datetime.now().isoformat()
            if details:
                log_line = f"{timestamp} | {action} | {username} (uid={uid}) | {details}\n"
            else:
                log_line = f"{timestamp} | {action} | {username} (uid={uid})\n"
            
            with open(self.screen_share_log_path, 'a', encoding='utf-8') as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"Failed to write screen share log: {e}")

    async def handle_file_upload(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, 
                                 session_info: dict):
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
                    chunk_size = min(8192, expected_size - bytes_received)
                    data = await reader.read(chunk_size)
                    
                    if not data:
                        logger.warning(f"Connection closed before upload complete: {bytes_received}/{expected_size} bytes")
                        break
                    
                    f.write(data)
                    bytes_received += len(data)
                    
                    # Log progress every 1MB
                    if bytes_received % (1024 * 1024) < 8192:
                        progress = (bytes_received / expected_size) * 100
                        logger.info(f"Upload progress [{fid}]: {bytes_received}/{expected_size} bytes ({progress:.1f}%)")
            
            if bytes_received == expected_size:
                logger.info(f"✓ FILE UPLOAD SUCCESS: '{filename}' ({bytes_received} bytes)")
                logger.info(f"  Uploader: {uploader} (uid={uid})")
                logger.info(f"  File ID: {fid}")
                logger.info(f"  Location: {file_path}")
                
                # Log to transfer log
                self.log_transfer("UPLOAD", filename, uploader, None, fid, bytes_received)
                
                # Store file metadata
                async with self.lock:
                    self.files[fid] = {
                        'fid': fid,
                        'filename': filename,
                        'size': bytes_received,
                        'uploader': uploader,
                        'uploader_uid': uid,
                        'path': str(file_path),
                        'uploaded_at': datetime.now().isoformat()
                    }
                
                # Broadcast file availability
                await self.broadcast({
                    "type": "file_available",
                    "fid": fid,
                    "filename": filename,
                    "size": bytes_received,
                    "uploader": uploader,
                    "timestamp": datetime.now().isoformat()
                })
                
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

    async def handle_file_download(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                                   session_info: dict):
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
                    data = f.read(8192)
                    if not data:
                        break
                    
                    writer.write(data)
                    await writer.drain()
                    bytes_sent += len(data)
                    
                    # Log progress every 1MB
                    if bytes_sent % (1024 * 1024) < 8192:
                        progress = (bytes_sent / file_size) * 100
                        logger.info(f"Download progress [{fid[:8]}...]: {bytes_sent}/{file_size} bytes ({progress:.1f}%)")
            
            logger.info(f"✓ FILE DOWNLOAD SUCCESS: '{filename}' ({bytes_sent} bytes)")
            logger.info(f"  Transfer: {uploader} → {requester}")
            
            # Log to transfer log
            self.log_transfer("DOWNLOAD", filename, uploader, requester, fid, bytes_sent)
        
        except Exception as e:
            logger.error(f"Error during file download: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def handle_login(self, uid: int, data: dict):
        """Process login message."""
        username = data.get('username', f'user_{uid}')
        
        async with self.lock:
            self.participants[uid] = {
                "uid": uid,
                "username": username,
                "joined_at": datetime.now().isoformat()
            }
        
        logger.info(f"User '{username}' logged in with uid={uid}")
        
        # Send confirmation to the client
        await self.send_message(uid, {
            "type": "login_success",
            "uid": uid,
            "username": username
        })
        
        # Broadcast user_joined to all clients
        await self.broadcast({
            "type": "user_joined",
            "uid": uid,
            "username": username,
            "timestamp": datetime.now().isoformat()
        })
        
        # Send current participant list to the new user
        async with self.lock:
            participants_list = list(self.participants.values())
        
        await self.send_message(uid, {
            "type": "participant_list",
            "participants": participants_list
        })

    async def handle_heartbeat(self, uid: int, data: dict):
        """Process heartbeat message."""
        logger.debug(f"Heartbeat from uid={uid}")
        # Respond with heartbeat_ack
        await self.send_message(uid, {
            "type": "heartbeat_ack",
            "timestamp": datetime.now().isoformat()
        })

    async def handle_chat(self, uid: int, data: dict):
        """Process chat message and broadcast to all."""
        # Support both "text" and "message" fields for compatibility
        message_text = data.get('text', data.get('message', ''))
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        logger.info(f"Chat from {username} (uid={uid}): {message_text}")
        
        # Create stamped chat message
        chat_message = {
            "type": "chat",
            "uid": uid,
            "username": username,
            "text": message_text,
            "timestamp": datetime.now().isoformat()
        }
        
        # Store in chat history
        async with self.lock:
            self.chat_history.append(chat_message)
        
        # Log to chat log file
        self.log_chat(username, uid, message_text)
        
        # Broadcast chat message to all clients
        await self.broadcast(chat_message)

    async def handle_broadcast(self, uid: int, data: dict):
        """Process broadcast message and send to all users."""
        message_text = data.get('text', data.get('message', ''))
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        logger.info(f"📢 BROADCAST from {username} (uid={uid}): {message_text}")
        
        # Create broadcast message
        broadcast_message = {
            "type": "broadcast",
            "uid": uid,
            "username": username,
            "text": message_text,
            "timestamp": datetime.now().isoformat()
        }
        
        # Store in chat history
        async with self.lock:
            self.chat_history.append(broadcast_message)
        
        # Log to chat log file
        self.log_chat(f"[BROADCAST] {username}", uid, message_text)
        
        # Broadcast to all clients
        await self.broadcast(broadcast_message)

    async def handle_unicast(self, uid: int, data: dict):
        """Process unicast message and send to specific user."""
        message_text = data.get('text', data.get('message', ''))
        target_uid = data.get('target_uid')
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        if not target_uid:
            await self.send_message(uid, {
                "type": "error",
                "message": "Missing target_uid for unicast"
            })
            return
        
        # Check if target user exists
        async with self.lock:
            if target_uid not in self.participants:
                await self.send_message(uid, {
                    "type": "error",
                    "message": f"User with uid={target_uid} not found"
                })
                return
            
            target_username = self.participants[target_uid]['username']
        
        logger.info(f"📨 UNICAST from {username} (uid={uid}) to {target_username} (uid={target_uid}): {message_text}")
        
        # Create unicast message
        unicast_message = {
            "type": "unicast",
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
        
        # Log to chat log file
        self.log_chat(f"[UNICAST {username}→{target_username}]", uid, message_text)
        
        # Send to target user
        await self.send_message(target_uid, unicast_message)
        
        # Send confirmation to sender
        await self.send_message(uid, {
            "type": "unicast_sent",
            "to_uid": target_uid,
            "to_username": target_username,
            "message": "Message sent successfully"
        })

    async def handle_file_offer(self, uid: int, data: dict):
        """Process file offer and set up upload port."""
        filename = data.get('filename', '')
        size = data.get('size', 0)
        fid = data.get('fid', '')
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        if not fid or not filename or size <= 0:
            logger.error(f"Invalid file offer from uid={uid}: missing fid/filename/size")
            await self.send_message(uid, {
                "type": "error",
                "message": "Invalid file offer: missing fid, filename, or size"
            })
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
            upload_server = await asyncio.start_server(accept_upload, self.host, upload_port)
            logger.info(f"Upload server started on port {upload_port} for fid={fid}")
            
            # Reply to client with upload port
            await self.send_message(uid, {
                "type": "file_upload_port",
                "fid": fid,
                "port": upload_port
            })
            
            # Schedule server cleanup after upload timeout (5 minutes)
            async def cleanup_server():
                await asyncio.sleep(300)  # 5 minute timeout
                upload_server.close()
                await upload_server.wait_closed()
                async with self.lock:
                    if upload_port in self.upload_sessions:
                        del self.upload_sessions[upload_port]
                logger.info(f"Upload server on port {upload_port} timed out and closed")
            
            asyncio.create_task(cleanup_server())
        
        except Exception as e:
            logger.error(f"Failed to start upload server on port {upload_port}: {e}")
            await self.send_message(uid, {
                "type": "error",
                "message": f"Failed to start upload server: {e}"
            })
            async with self.lock:
                if upload_port in self.upload_sessions:
                    del self.upload_sessions[upload_port]

    async def handle_file_request(self, uid: int, data: dict):
        """Process file download request and set up download port."""
        fid = data.get('fid', '')
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        if not fid:
            logger.error(f"Invalid file request from uid={uid}: missing fid")
            await self.send_message(uid, {
                "type": "error",
                "message": "Invalid file request: missing fid"
            })
            return
        
        # Check if file exists
        async with self.lock:
            file_info = self.files.get(fid)
        
        if not file_info:
            logger.warning(f"File request from {username} (uid={uid}) for unknown fid={fid}")
            await self.send_message(uid, {
                "type": "error",
                "message": f"File not found: fid={fid}"
            })
            return
        
        uploader = file_info['uploader']
        filename = file_info['filename']
        
        logger.info(f"📥 FILE REQUEST: {username} (uid={uid}) wants '{filename}' from {uploader}")
        logger.info(f"  File ID: {fid}")
        
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
            download_server = await asyncio.start_server(accept_download, self.host, download_port)
            logger.info(f"Download server started on port {download_port} for fid={fid}")
            
            # Reply to client with download port
            await self.send_message(uid, {
                "type": "file_download_port",
                "fid": fid,
                "filename": file_info['filename'],
                "size": file_info['size'],
                "port": download_port
            })
            
            # Schedule server cleanup after download timeout (5 minutes)
            async def cleanup_server():
                await asyncio.sleep(300)  # 5 minute timeout
                download_server.close()
                await download_server.wait_closed()
                async with self.lock:
                    if download_port in self.download_sessions:
                        del self.download_sessions[download_port]
                logger.info(f"Download server on port {download_port} timed out and closed")
            
            asyncio.create_task(cleanup_server())
        
        except Exception as e:
            logger.error(f"Failed to start download server on port {download_port}: {e}")
            await self.send_message(uid, {
                "type": "error",
                "message": f"Failed to start download server: {e}"
            })
            async with self.lock:
                if download_port in self.download_sessions:
                    del self.download_sessions[download_port]

    async def relay_frames(self, presenter_reader: asyncio.StreamReader):
        """Relay frames from presenter to all viewers."""
        logger.info("[SCREEN SHARE] Starting frame relay")
        
        try:
            while self.presentation_active:
                # Read frame from presenter
                try:
                    # Read 4-byte frame length header
                    length_data = await presenter_reader.readexactly(4)
                    import struct
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

    async def handle_present_start(self, uid: int, data: dict):
        """Start screen sharing presentation."""
        username = self.participants.get(uid, {}).get('username', 'unknown')
        topic = data.get('topic', 'Screen Share')
        
        # Check if presentation already active
        if self.presentation_active:
            logger.warning(f"Presentation already active by {self.presenter_username}")
            await self.send_message(uid, {
                "type": "error",
                "message": f"Presentation already active by {self.presenter_username}"
            })
            return
        
        logger.info(f"🎬 SCREEN SHARE STARTING: {username} (uid={uid}) - {topic}")
        
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
        self.log_screen_share(
            "START", username, uid, 
            f"Topic: {topic} | Presenter Port: {self.presenter_port} | Viewer Port: {self.viewer_port}"
        )
        
        # Start presenter server
        async def accept_presenter(reader, writer):
            self.presenter_writer = writer
            addr = writer.get_extra_info('peername')
            logger.info(f"[SCREEN SHARE] Presenter connected from {addr}")
            
            # Start frame relay
            self.frame_relay_task = asyncio.create_task(self.relay_frames(reader))
        
        try:
            presenter_server = await asyncio.start_server(
                accept_presenter, self.host, self.presenter_port
            )
            logger.info(f"[SCREEN SHARE] Presenter server started on port {self.presenter_port}")
            
            # Start viewer server
            async def accept_viewer(reader, writer):
                # Viewers are stored and frames are relayed to them
                viewer_addr = writer.get_extra_info('peername')
                logger.info(f"[SCREEN SHARE] Viewer connected from {viewer_addr}")
                
                # Log viewer connection
                self.log_screen_share(
                    "VIEWER_JOIN", self.presenter_username, self.presenter_uid,
                    f"Viewer from {viewer_addr}"
                )
                
                async with self.lock:
                    # Use a unique ID for this viewer connection
                    viewer_id = id(writer)
                    self.viewers[viewer_id] = writer
            
            viewer_server = await asyncio.start_server(
                accept_viewer, self.host, self.viewer_port
            )
            logger.info(f"[SCREEN SHARE] Viewer server started on port {self.viewer_port}")
            
            # Reply to presenter with ports
            await self.send_message(uid, {
                "type": "screen_share_ports",
                "presenter_port": self.presenter_port,
                "viewer_port": self.viewer_port
            })
            
            # Broadcast to all clients
            await self.broadcast({
                "type": "present_start",
                "uid": uid,
                "username": username,
                "topic": topic,
                "viewer_port": self.viewer_port,
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(f"[SCREEN SHARE] Broadcast sent to all clients")
        
        except Exception as e:
            logger.error(f"Failed to start screen sharing: {e}")
            self.presentation_active = False
            self.presenter_uid = None
            self.presenter_username = None
            await self.send_message(uid, {
                "type": "error",
                "message": f"Failed to start screen sharing: {e}"
            })

    async def handle_present_stop(self, uid: int, data: dict):
        """Stop screen sharing presentation."""
        username = self.participants.get(uid, {}).get('username', 'unknown')
        
        if not self.presentation_active:
            logger.warning(f"No active presentation to stop")
            return
        
        if uid != self.presenter_uid:
            logger.warning(f"{username} tried to stop presentation by {self.presenter_username}")
            await self.send_message(uid, {
                "type": "error",
                "message": "You are not the presenter"
            })
            return
        
        logger.info(f"🎬 SCREEN SHARE STOPPED: {username} (uid={uid})")
        
        # Log screen share stop
        num_viewers = len(self.viewers)
        self.log_screen_share(
            "STOP", username, uid,
            f"Duration: presentation ended | Viewers: {num_viewers}"
        )
        
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
        await self.broadcast({
            "type": "present_stop",
            "uid": uid,
            "username": username,
            "timestamp": datetime.now().isoformat()
        })

    async def handle_logout(self, uid: int, data: dict):
        """Process logout message."""
        logger.info(f"Logout request from uid={uid}")
        await self.disconnect_client(uid)

    async def handle_get_history(self, uid: int, data: dict):
        """Send chat history to requesting client."""
        logger.info(f"Chat history requested by uid={uid}")
        
        # Get chat history as a list (thread-safe copy)
        async with self.lock:
            history_list = list(self.chat_history)
        
        # Send history to the requesting client
        await self.send_message(uid, {
            "type": "history",
            "messages": history_list,
            "count": len(history_list)
        })

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle individual client connection."""
        addr = writer.get_extra_info('peername')
        
        # Assign uid to client
        async with self.lock:
            uid = self.next_uid
            self.next_uid += 1
            self.clients[uid] = writer
        
        logger.info(f"New connection from {addr}, assigned uid={uid}")
        
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
                    if msg_type == 'login':
                        await self.handle_login(uid, message)
                    elif msg_type == 'heartbeat':
                        await self.handle_heartbeat(uid, message)
                    elif msg_type == 'chat':
                        await self.handle_chat(uid, message)
                    elif msg_type == 'broadcast':
                        await self.handle_broadcast(uid, message)
                    elif msg_type == 'unicast':
                        await self.handle_unicast(uid, message)
                    elif msg_type == 'get_history':
                        await self.handle_get_history(uid, message)
                    elif msg_type == 'file_offer':
                        await self.handle_file_offer(uid, message)
                    elif msg_type == 'file_request':
                        await self.handle_file_request(uid, message)
                    elif msg_type == 'present_start':
                        await self.handle_present_start(uid, message)
                    elif msg_type == 'present_stop':
                        await self.handle_present_stop(uid, message)
                    elif msg_type == 'logout':
                        await self.handle_logout(uid, message)
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
            self.host,
            self.port
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
        logger.error(f"Server error: {e}")

