# LAN Multi-User Collaboration Server/Client

Python 3 asyncio-based server and client for LAN collaboration with control message support.

## Files

- `server_control.py` - Main server listening on TCP port 9000
- `client_control.py` - Interactive client with chat, file transfer, and screen sharing (all-in-one)
- `uploads/` - Directory where server stores uploaded files
- `downloads/` - Directory where client saves downloaded files
- `logs/` - Server logs directory (auto-created)
  - `chat_history.log` - All chat messages with timestamps
  - `file_transfers.log` - All file uploads/downloads with user tracking
  - `screen_sharing.log` - All screen sharing sessions with viewer counts
  - `EXAMPLE_*.log` - Example log files showing format
- `requirements.txt` - Dependencies for screen sharing
- `LOGGING_GUIDE.md` - Complete guide to viewing and analyzing logs
- `IMPLEMENTATION_COMPLETE.md` - Implementation summary and testing guide

## Requirements

### Basic Features (Chat, File Transfer)

- Python 3.7+
- No external dependencies (uses standard library only)

### Screen Sharing (Optional)
- Python 3.7+
- Additional packages: `mss`, `Pillow`, `PyQt5`

Install with:

```powershell
> pip install -r requirements.txt
```

## Quick Start

### 1. Start the Server

```powershell
> python server_control.py
```

The server will listen on `0.0.0.0:9000` and accept multiple concurrent connections.

### 2. Run Multiple Clients

**Terminal 1:**
```powershell
> python client_control.py Alice
```

**Terminal 2:**
```powershell
> python client_control.py Bob
```

**Terminal 3:**
```powershell
> python client_control.py Charlie
```

Each client will:
- Connect and login with the provided username
- Receive broadcasts when other users join/leave
- Send heartbeat every 10 seconds
- Allow typing chat messages
- Cleanly logout on Ctrl+C

### 3. Broadcast and Unicast Messages

The system supports different types of messaging:

**Broadcast Messages (to all users):**
```powershell
> /broadcast Important announcement for everyone!
📢 [BROADCAST] Alice: Important announcement for everyone!
```

**Private Messages (to specific user):**
```powershell
> /unicast 2 Hey Bob, can you check the file?
✓ [SENT] Private message delivered to Bob (uid=2)
```

**Regular Chat (same as broadcast):**
```powershell
> Hello everyone!
[CHAT] Alice: Hello everyone!
```

### 4. File Transfer

The system supports file uploads and downloads using commands in the interactive client.

**Start client and use commands:**
```powershell
> python client_control.py Alice

[INFO] Type messages to chat (Ctrl+C to exit)
[INFO] Commands: /upload <file>, /download <fid> [path], /broadcast <msg>, /unicast <uid> <msg>, /help

> /upload document.pdf
[UPLOAD] Offering file: document.pdf (12345 bytes, fid=abc-123-def)
[UPLOAD] Upload complete: document.pdf

> Hello everyone!
[CHAT] Bob: Hi Alice!

> /help
[HELP] Available commands:
  /upload <file_path>        - Upload a file
  /download <fid> [path]     - Download a file by fid
  /broadcast <message>       - Send message to all users
  /unicast <uid> <message>   - Send private message to user
  /help                      - Show this help
```

**Download from another client:**
```powershell
> python client_control.py Bob

[FILE] Available: document.pdf (12345 bytes) from Alice [fid=abc-123-def]

> /download abc-123-def
[DOWNLOAD] Saving to: downloads/document.pdf
[DOWNLOAD] Download complete: downloads/document.pdf

# Or specify custom path:
> /download abc-123-def reports/my_document.pdf
[DOWNLOAD] Saving to: reports/my_document.pdf
[DOWNLOAD] Download complete: reports/my_document.pdf
```

File transfer features:
- Upload and download without leaving chat session
- Server stores uploaded files in `uploads/` directory
- Client saves downloaded files to `downloads/` directory (auto-created)
- Custom save path supported: `/download <fid> custom/path/file.pdf`
- Server assigns ephemeral ports (10000+) for each transfer
- Progress logging every 1MB
- Automatic cleanup of failed transfers
- Broadcast notifications when files become available

### 5. Screen Sharing

Share your screen with all participants in real-time.

**Install dependencies first:**
```powershell
> pip install -r requirements.txt
```

**Start screen sharing:**
```powershell
> python client_control.py Alice

> /present
[PRESENT] Starting screen share...
[PRESENT] Your presentation 'Alice's Screen' is now live!
[PRESENTER] Frames: 30, FPS: 3.0, Frame size: 45.2 KB
```

**View someone's screen:**
```powershell
> python client_control.py Bob

[PRESENT] 🎬 Alice started presentation: Alice's Screen
[PRESENT] Type '/view' to watch

> /view
[VIEW] Opening Alice's screen...
```

A PyQt window opens displaying Alice's screen in real-time!

**Stop sharing:**
```powershell
> /stopshare
[PRESENT] Stopped
```

Screen sharing features:
- Real-time screen capture at adjustable FPS (2-5 default)
- JPEG compression with configurable quality (default 70%)
- Resolution scaling (default 0.5x for lower bandwidth)
- Dedicated TCP streaming for smooth playback
- Multiple viewers supported simultaneously
- PyQt5 viewer with auto-scaling display
- Low bandwidth usage (30-150 KB/s typical)
- Integrated directly into client code

## Testing with curl (Windows PowerShell)

**Send login message:**
```powershell
> echo '{"type":"login","username":"curl_user"}' | curl telnet://localhost:9000
```

**Note:** curl's telnet support is limited. For better testing, use netcat or the Python clients.

## Testing with PowerShell TCP Client

```powershell
> $client = New-Object System.Net.Sockets.TcpClient("localhost", 9000)
> $stream = $client.GetStream()
> $writer = New-Object System.IO.StreamWriter($stream)
> $writer.WriteLine('{"type":"login","username":"ps_user"}')
> $writer.Flush()
> $reader = New-Object System.IO.StreamReader($stream)
> $reader.ReadLine()
```

## Supported Message Types

### Client to Server:
- `login` - Initial authentication with username
- `heartbeat` - Keep-alive signal
- `chat` - Send chat message to all users (field: "text")
- `broadcast` - Send broadcast message to all users (field: "text")
- `unicast` - Send private message to specific user (target_uid, text)
- `get_history` - Request chat history (last 500 messages)
- `file_offer` - Offer file for upload (fid, filename, size)
- `file_request` - Request file download (fid)
- `present_start` - Start screen sharing presentation
- `present_stop` - Stop screen sharing presentation
- `logout` - Graceful disconnect

### Server to Client:
- `login_success` - Confirmation with assigned uid
- `participant_list` - Current connected users
- `history` - Chat history with timestamped messages
- `user_joined` - Broadcast when user connects
- `user_left` - Broadcast when user disconnects
- `heartbeat_ack` - Heartbeat response
- `chat` - Broadcast chat message (stamped with uid, username, timestamp)
- `broadcast` - Broadcast message to all users (stamped with uid, username, timestamp)
- `unicast` - Private message (from_uid, from_username, to_uid, to_username, text, timestamp)
- `unicast_sent` - Confirmation that private message was delivered
- `file_upload_port` - Reply with ephemeral port for upload
- `file_download_port` - Reply with ephemeral port for download
- `file_available` - Broadcast when file upload completes
- `screen_share_ports` - Reply with presenter and viewer ports
- `present_start` - Broadcast screen sharing started (includes viewer_port)
- `present_stop` - Broadcast screen sharing stopped
- `error` - Error message

## Architecture

- **Asyncio-based**: Non-blocking concurrent client handling
- **Line-delimited JSON**: Each message is a JSON object followed by newline
- **In-memory state**: Participant list maintained in memory
- **Chat history**: Server stores last 500 messages with timestamps
- **File transfer**: Dual-channel system (control + ephemeral data ports)
  - Control messages on port 9000
  - File data on ephemeral ports (10000+)
  - Each transfer gets dedicated port with 5-minute timeout
  - Automatic cleanup of failed/incomplete transfers
- **Graceful error handling**: Malformed JSON and socket errors handled safely
- **Broadcast system**: Events automatically sent to all connected clients
- **Auto-history**: Clients automatically receive chat history on login

## Example Session

```text
# Server Output
2025-10-24 10:30:01 [INFO] Server listening on ('0.0.0.0', 9000)
2025-10-24 10:30:05 [INFO] New connection from ('127.0.0.1', 54321), assigned uid=1
2025-10-24 10:30:05 [INFO] User 'Alice' logged in with uid=1
2025-10-24 10:30:12 [INFO] New connection from ('127.0.0.1', 54322), assigned uid=2
2025-10-24 10:30:12 [INFO] User 'Bob' logged in with uid=2
2025-10-24 10:30:18 [INFO] Chat from Alice (uid=1): Hello Bob!
2025-10-24 10:30:24 [INFO] Chat from Bob (uid=2): Hi Alice!
2025-10-24 10:30:30 [INFO] 📢 BROADCAST from Alice (uid=1): Important meeting at 3 PM
2025-10-24 10:30:35 [INFO] 📨 UNICAST from Alice (uid=1) to Bob (uid=2): Can you prepare the report?

# Client 1 (Alice) Output
[INFO] Connected to localhost:9000
[INFO] Logging in as 'Alice'...
[SUCCESS] Logged in as 'Alice' with uid=1
[INFO] Current participants (1):
  - Alice (uid=1)
[INFO] Type messages to chat (Ctrl+C to exit)
Hello Bob!
[EVENT] User 'Bob' joined (uid=2)
[CHAT] Bob: Hi Alice!
> /broadcast Important meeting at 3 PM
> /unicast 2 Can you prepare the report?
✓ [SENT] Private message delivered to Bob (uid=2)

# Client 2 (Bob) Output
[INFO] Connected to localhost:9000
[INFO] Logging in as 'Bob'...
[SUCCESS] Logged in as 'Bob' with uid=2
[INFO] Current participants (2):
  - Alice (uid=1)
  - Bob (uid=2)
[HISTORY] No previous messages
[INFO] Type messages to chat (Ctrl+C to exit)
[CHAT] Alice: Hello Bob!
Hi Alice!
📢 [BROADCAST] Alice: Important meeting at 3 PM
📨 [PRIVATE] Alice → Bob: Can you prepare the report?

# Client 3 (Charlie) - Joins Later and Sees History
[INFO] Connected to localhost:9000
[INFO] Logging in as 'Charlie'...
[SUCCESS] Logged in as 'Charlie' with uid=3
[INFO] Current participants (3):
  - Alice (uid=1)
  - Bob (uid=2)
  - Charlie (uid=3)

[HISTORY] Loading 4 previous message(s):
--------------------------------------------------
[2025-10-24 10:30:18] Alice: Hello Bob!
[2025-10-24 10:30:24] Bob: Hi Alice!
[2025-10-24 10:30:30] [BROADCAST] Alice: Important meeting at 3 PM
[2025-10-24 10:30:35] [UNICAST Alice→Bob] Alice: Can you prepare the report?
--------------------------------------------------
[INFO] Type messages to chat (Ctrl+C to exit)
```

## File Transfer Example

```text
# Terminal 1: Alice uploads a file
> python client_control.py Alice

[INFO] Type messages to chat (Ctrl+C to exit)
[INFO] Commands: /upload <file>, /download <fid> [path], /broadcast <msg>, /unicast <uid> <msg>, /help

> /upload report.pdf
[UPLOAD] Offering file: report.pdf (2048576 bytes, fid=a1b2c3d4-...)
[UPLOAD] Received upload port 10000 for fid=a1b2c3d4-...
[UPLOAD] Connecting to upload port 10000...
[UPLOAD] Uploading report.pdf...
[UPLOAD] Progress: 1048576/2048576 bytes (51.2%)
[UPLOAD] Progress: 2048576/2048576 bytes (100.0%)
[UPLOAD] Upload complete: report.pdf

> File uploaded successfully!

# Terminal 2: Bob sees broadcast and downloads
> python client_control.py Bob

[INFO] Connected to localhost:9000
[SUCCESS] Logged in as 'Bob' with uid=2
[FILE] Available: report.pdf (2048576 bytes) from Alice [fid=a1b2c3d4-...]
[CHAT] Alice: File uploaded successfully!

> Thanks! Downloading now...
> /download a1b2c3d4-... my_report.pdf
[DOWNLOAD] Requesting file with fid=a1b2c3d4-...
[DOWNLOAD] Received download port 10001 for report.pdf
[DOWNLOAD] Connecting to download port 10001...
[DOWNLOAD] Downloading report.pdf...
[DOWNLOAD] Progress: 1048576/2048576 bytes (51.2%)
[DOWNLOAD] Progress: 2048576/2048576 bytes (100.0%)
[DOWNLOAD] Download complete: downloads/my_report.pdf

> Got it!

# Server Output
2025-10-24 10:35:00 [INFO] File offer from Alice (uid=1): report.pdf (2048576 bytes, fid=a1b2c3d4-...)
2025-10-24 10:35:00 [INFO] Upload server started on port 10000 for fid=a1b2c3d4-...
2025-10-24 10:35:01 [INFO] File upload connection from ('127.0.0.1', 54321) for fid=a1b2c3d4-...
2025-10-24 10:35:01 [INFO] Upload progress [a1b2c3d4-...]: 1048576/2048576 bytes (51.2%)
2025-10-24 10:35:02 [INFO] ✓ FILE UPLOAD SUCCESS: 'report.pdf' (2048576 bytes)
2025-10-24 10:35:02 [INFO]   Uploader: Alice (uid=1)
2025-10-24 10:35:02 [INFO]   File ID: a1b2c3d4-...
2025-10-24 10:35:02 [INFO]   Location: uploads/report.pdf
2025-10-24 10:35:02 [INFO]   Broadcast sent to all clients
2025-10-24 10:35:10 [INFO] Chat from Alice (uid=1): File uploaded successfully!
2025-10-24 10:35:15 [INFO] Chat from Bob (uid=2): Thanks! Downloading now...
2025-10-24 10:35:16 [INFO] 📥 FILE REQUEST: Bob (uid=2) wants 'report.pdf' from Alice
2025-10-24 10:35:16 [INFO]   File ID: a1b2c3d4-...
2025-10-24 10:35:16 [INFO] Download server started on port 10001 for fid=a1b2c3d4-...
2025-10-24 10:35:17 [INFO] ⬇ FILE TRANSFER STARTED
2025-10-24 10:35:17 [INFO]   File: 'report.pdf' (fid=a1b2c3d4...)
2025-10-24 10:35:17 [INFO]   From: Alice (uid=1)
2025-10-24 10:35:17 [INFO]   To: Bob (uid=2)
2025-10-24 10:35:17 [INFO] Download progress [a1b2c3d4...]: 1048576/2048576 bytes (51.2%)
2025-10-24 10:35:18 [INFO] ✓ FILE DOWNLOAD SUCCESS: 'report.pdf' (2048576 bytes)
2025-10-24 10:35:18 [INFO]   Transfer: Alice → Bob
2025-10-24 10:35:20 [INFO] Chat from Bob (uid=2): Got it!
```

## Activity Logging

All activities are logged to the `logs/` directory:

### 1. Chat Log (`logs/chat_history.log`)

Every chat message is logged with timestamp and user:

```text
2025-10-24T10:30:15 | Alice (uid=1) | Hello everyone!
2025-10-24T10:30:20 | Bob (uid=2) | Hi Alice!
2025-10-24T10:30:25 | Charlie (uid=3) | Hey guys!
2025-10-24T10:30:30 | [BROADCAST] Alice (uid=1) | Important meeting at 3 PM
2025-10-24T10:30:35 | [UNICAST Alice→Bob] Alice (uid=1) | Can you prepare the report?
```

### 2. File Transfer Log (`logs/file_transfers.log`)

All file uploads and downloads:

```text
2025-10-24T10:35:02 | UPLOAD | report.pdf | USER: Alice | SIZE: 2048576 bytes | FID: a1b2c3d4-...
2025-10-24T10:35:18 | DOWNLOAD | report.pdf | FROM: Alice | TO: Bob | SIZE: 2048576 bytes | FID: a1b2c3d4-...
2025-10-24T10:36:45 | DOWNLOAD | report.pdf | FROM: Alice | TO: Charlie | SIZE: 2048576 bytes | FID: a1b2c3d4-...
```

### 3. Screen Sharing Log (`logs/screen_sharing.log`)

All presentation sessions and viewers:

```text
2025-10-24T10:40:00 | START | Alice (uid=1) | Topic: Alice's Screen | Presenter Port: 10002 | Viewer Port: 10003
2025-10-24T10:40:05 | VIEWER_JOIN | Alice (uid=1) | Viewer from ('127.0.0.1', 54322)
2025-10-24T10:40:10 | VIEWER_JOIN | Alice (uid=1) | Viewer from ('127.0.0.1', 54323)
2025-10-24T10:42:30 | STOP | Alice (uid=1) | Duration: presentation ended | Viewers: 2
```

### Console Output

Server also displays real-time logs with emojis:

```text
✓ FILE UPLOAD SUCCESS: 'report.pdf' (2048576 bytes)
  Uploader: Alice (uid=1)

📥 FILE REQUEST: Bob (uid=2) wants 'report.pdf' from Alice

🎬 SCREEN SHARE STARTING: Alice (uid=1) - Alice's Screen
  Presenter port: 10002
  Viewer port: 10003
```

## Viewing Activity Logs

All logs are stored in the `logs/` directory and persist across server restarts.

**View chat history:**
```powershell
> type logs\chat_history.log
```

**View file transfers:**
```powershell
> type logs\file_transfers.log
```

**View screen sharing sessions:**
```powershell
> type logs\screen_sharing.log
```

**Monitor logs in real-time:**
```powershell
> Get-Content logs\chat_history.log -Wait -Tail 10
```

**Search logs:**
```powershell
# Find all messages from Alice
> Select-String "Alice" logs\chat_history.log

# Find all file downloads
> Select-String "DOWNLOAD" logs\file_transfers.log

# Find all screen share sessions
> Select-String "START" logs\screen_sharing.log
```

## Notes

- **Comprehensive Logging**: All activities logged to `logs/` directory
  - `chat_history.log` - Every chat message with timestamp and user
  - `file_transfers.log` - All uploads/downloads with user tracking
  - `screen_sharing.log` - Presentation sessions and viewer connections
  - Logs are append-only and persistent across server restarts
  - **Broadcast messages** - All broadcasts logged with sender info
  - **Private messages** - Unicast messages logged with sender/receiver pairs
  
- **Chat history**: Server stores last 500 messages in memory; new clients automatically receive history on login

- **File transfer**: Fully implemented with upload/download support
  - Files stored in `uploads/` directory on server
  - UUID-based file identifiers (fid)
  - Ephemeral ports for each transfer (10000+)
  - 5-minute timeout per transfer session
  - Progress logging every 1MB
  - Automatic cleanup of incomplete transfers

- **Screen sharing**: Real-time screen capture and streaming
  - Presenter streams at 2-5 FPS with JPEG compression
  - Multiple viewers supported simultaneously
  - Dedicated ports for presenter/viewers
  - PyQt5 viewer with smooth display
  - All integrated into `client_control.py`
  - Viewer connections tracked in logs

- Chat messages use "text" field (backward compatible with "message" field)
- Clients automatically reconnect behavior not implemented (manual restart required)
- No authentication/encryption (LAN use only)