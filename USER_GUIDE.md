# LAN Collaboration System - Complete User Guide

## Overview

A fully-featured, Zoom-like collaboration application for local area networks with complete feature parity including video conferencing, audio communication, screen sharing, text chat, and file sharing.

## Features

### ✅ Complete Feature Set

1. **Video Communication**
   - Real-time video streaming with webcam
   - Multiple participant video grid layout
   - Adjustable resolution (640x360 default)
   - Frame rate optimization (15 FPS default)
   - Automatic bandwidth adaptation
   - Gallery and speaker view layouts

2. **Audio Communication**
   - Bidirectional audio streaming
   - Real-time audio mixing on server
   - Opus codec for high-quality compression
   - Mute/unmute functionality
   - Per-participant volume control
   - Jitter buffer for smooth playback

3. **Screen Sharing**
   - Real-time screen capture and streaming
   - Adjustable quality settings (70% JPEG quality)
   - Frame rate control (3 FPS default)
   - Resolution scaling (0.5x default)
   - Minimal latency design
   - Multiple presenter support

4. **Text Chat**
   - Real-time messaging
   - Broadcast messages to all participants
   - Private (unicast) messages to specific users
   - Chat history with 500 message buffer
   - Message timestamps
   - System notifications

5. **File Sharing**
   - Upload files up to 100MB
   - Download shared files
   - Progress indicators
   - File metadata display
   - Automatic file availability notifications
   - Support for all file types

6. **Network Communication**
   - TCP for control messages (port 9000)
   - UDP for audio streaming (port 11000)
   - UDP for video streaming (port 10000)
   - Unicast for private messages
   - Broadcast for group messages
   - Multicast-ready architecture

7. **Participant Management**
   - Real-time participant list
   - User join/leave notifications
   - Participant mute controls
   - Username display
   - UID tracking

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Webcam (for video features)
- Microphone (for audio features)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Verify Installation

```bash
python main_app.py --check-deps
```

## Quick Start

### Starting the Server

```bash
# Start with default settings
python server/main_server.py

# Start with custom settings
python server/main_server.py --host 0.0.0.0 --port 9000 --audio-port 11000 --video-port 10000
```

### Starting the Client

```bash
# Connect to local server
python main_app.py

# Connect to remote server
python main_app.py --server 192.168.1.100

# Specify username
python main_app.py --username "John Doe"
```

## User Interface Guide

### Main Window Layout

```
┌─────────────────────────────────────────────────────────┐
│  LAN Collaboration Client - Username (Connected)        │
├─────────────────────────────────────┬───────────────────┤
│                                     │  Participants     │
│                                     │  ┌─────────────┐  │
│         Video Grid                  │  │ User 1 (You)│  │
│    (Multiple video feeds)           │  │ User 2   🔇 │  │
│                                     │  │ User 3   🔇 │  │
│                                     │  └─────────────┘  │
│                                     │                   │
│                                     │  Controls         │
│                                     │  🎤 Mute Audio    │
│                                     │  📹 Start Video   │
│                                     │  🖥️ Start Share   │
├─────────────────────────────────────┴───────────────────┤
│  Chat                                                    │
│  ┌────────────────────────────────────────────────────┐ │
│  │ [10:30] System: Connected to server                │ │
│  │ [10:31] User2: Hello everyone!                     │ │
│  └────────────────────────────────────────────────────┘ │
│  [Type a message...] [Send] [📎] [📢] [🔒]              │
└─────────────────────────────────────────────────────────┘
```

### Control Buttons

- **🎤 Mute/Unmute Audio**: Toggle your microphone
- **📹 Start/Stop Video**: Toggle your webcam
- **🖥️ Start/Stop Screen Share**: Share your screen
- **Send**: Send text message
- **📎**: Upload file
- **📢**: Send broadcast message
- **🔒**: Send private message

## Feature Usage

### Video Communication

1. **Start Video**:
   - Click "📹 Start Video" button
   - Your video feed appears in the grid
   - Other participants see your video

2. **Stop Video**:
   - Click "📹 Stop Video" button
   - Your video feed is removed

3. **View Others**:
   - Video feeds automatically appear when others start video
   - Grid layout adjusts automatically

### Audio Communication

1. **Unmute Audio**:
   - Click "🎤 Unmute Audio" button
   - Speak into your microphone
   - Audio is mixed with other participants

2. **Mute Audio**:
   - Click "🎤 Mute Audio" button
   - Your audio stops transmitting

3. **Mute Others**:
   - Click 🔇 button next to participant name
   - You won't hear that participant

### Screen Sharing

1. **Start Sharing**:
   - Click "🖥️ Start Screen Share"
   - Your screen is captured and streamed
   - Other participants receive notification

2. **View Shared Screen**:
   - When someone shares, you'll see a dialog
   - Click "Yes" to view their screen
   - Screen appears in a new window

3. **Stop Sharing**:
   - Click "🖥️ Stop Screen Share"
   - Sharing stops immediately

### Text Chat

1. **Send Message**:
   - Type in the input field
   - Press Enter or click "Send"
   - Message appears for all participants

2. **Broadcast Message**:
   - Type your message
   - Click 📢 button
   - Message sent to all with [BROADCAST] tag

3. **Private Message**:
   - Type your message
   - Click 🔒 button
   - Select recipient from dialog
   - Message sent privately

### File Sharing

1. **Upload File**:
   - Click 📎 button
   - Select file (max 100MB)
   - Wait for upload to complete
   - All participants notified

2. **Download File**:
   - Click "⬇️ Download" link in chat
   - Choose save location
   - Wait for download to complete

## Network Architecture

### Protocol Design

```
Client ←→ Server Communication:

1. Control Channel (TCP, Port 9000)
   - Login/logout
   - Chat messages
   - File metadata
   - Screen share control
   - Participant updates

2. Audio Channel (UDP, Port 11000)
   - Opus-encoded audio packets
   - 40ms frame duration
   - 48kHz sample rate
   - Server-side mixing

3. Video Channel (UDP, Port 10000)
   - JPEG-encoded frames
   - Chunked transmission
   - Frame reassembly on server
   - Broadcast to all clients
```

### Message Types

**Client → Server:**
- `login`: Authenticate with username
- `heartbeat`: Keep connection alive
- `chat`: Send text message
- `broadcast`: Send broadcast message
- `unicast`: Send private message
- `file_offer`: Offer file for upload
- `file_request`: Request file download
- `present_start`: Start screen sharing
- `present_stop`: Stop screen sharing
- `logout`: Disconnect

**Server → Client:**
- `login_success`: Login confirmed
- `participant_list`: Current participants
- `user_joined`: New user notification
- `user_left`: User disconnect notification
- `chat`: Incoming message
- `broadcast`: Incoming broadcast
- `unicast`: Incoming private message
- `file_available`: File ready for download
- `file_upload_port`: Port for upload
- `file_download_port`: Port for download
- `present_start_broadcast`: Screen share started
- `present_stop_broadcast`: Screen share stopped
- `error`: Error message

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to server

**Solutions**:
1. Verify server is running
2. Check IP address and port
3. Disable firewall or add exceptions
4. Ensure network connectivity

### Audio Issues

**Problem**: No audio transmission

**Solutions**:
1. Check microphone permissions
2. Verify sounddevice installation
3. Test microphone in system settings
4. Check audio button is unmuted

**Problem**: Audio quality poor

**Solutions**:
1. Check network bandwidth
2. Reduce number of participants
3. Close other network applications
4. Move closer to router

### Video Issues

**Problem**: No video feed

**Solutions**:
1. Check webcam permissions
2. Verify opencv-python installation
3. Test webcam in other applications
4. Ensure webcam is not in use

**Problem**: Video lag or freezing

**Solutions**:
1. Reduce video resolution
2. Lower frame rate
3. Check network bandwidth
4. Close other applications

### Screen Sharing Issues

**Problem**: Screen share not working

**Solutions**:
1. Verify mss and Pillow installed
2. Check screen capture permissions
3. Try restarting application
4. Check server logs for errors

### File Sharing Issues

**Problem**: File upload fails

**Solutions**:
1. Check file size (max 100MB)
2. Verify disk space on server
3. Check network connection
4. Try smaller file first

**Problem**: File download fails

**Solutions**:
1. Verify file still available
2. Check disk space on client
3. Ensure write permissions
4. Try different save location

## Performance Optimization

### Network Optimization

1. **Use Wired Connection**: Ethernet provides better stability than WiFi
2. **Close Background Apps**: Reduce network congestion
3. **Limit Participants**: Fewer participants = better performance
4. **Adjust Quality Settings**: Lower quality for slower networks

### System Optimization

1. **Close Unnecessary Apps**: Free up CPU and memory
2. **Update Drivers**: Ensure webcam and audio drivers are current
3. **Disable Antivirus Scanning**: Temporarily for better performance
4. **Use SSD**: Faster disk for file operations

### Application Settings

1. **Video Resolution**: Lower for better performance
   - Default: 640x360
   - Low bandwidth: 320x180

2. **Video Frame Rate**: Adjust based on network
   - Default: 15 FPS
   - Low bandwidth: 10 FPS

3. **Screen Share Quality**: Balance quality vs bandwidth
   - Default: 70% JPEG quality
   - Low bandwidth: 50%

4. **Screen Share FPS**: Lower for better performance
   - Default: 3 FPS
   - Low bandwidth: 2 FPS

## Security Considerations

### Network Security

1. **Use Private Networks**: Don't expose server to internet
2. **Firewall Rules**: Only allow necessary ports
3. **VPN**: Use VPN for remote access
4. **Authentication**: Implement user authentication (future)

### Data Security

1. **Local Storage**: Files stored locally on server
2. **No Encryption**: Currently no end-to-end encryption
3. **Temporary Files**: Clean up after sessions
4. **Access Control**: Implement file access controls (future)

## Advanced Usage

### Custom Server Configuration

```bash
# Bind to specific interface
python server/main_server.py --host 192.168.1.100

# Use custom ports
python server/main_server.py --port 9000 --audio-port 11000 --video-port 10000

# Custom upload directory
python server/main_server.py --upload-dir /path/to/uploads
```

### Multiple Servers

Run multiple servers on different ports for separate sessions:

```bash
# Session 1
python server/main_server.py --port 9000 --audio-port 11000 --video-port 10000

# Session 2
python server/main_server.py --port 9001 --audio-port 11001 --video-port 10001
```

### Programmatic Usage

```python
from client.ui.client_gui import ClientMainWindow
from PyQt6.QtWidgets import QApplication

app = QApplication([])
window = ClientMainWindow(server_host='192.168.1.100', server_port=9000)
window.show()
app.exec()
```

## System Requirements

### Minimum Requirements

- **OS**: Windows 10, macOS 10.14, Linux (Ubuntu 18.04+)
- **CPU**: Dual-core 2.0 GHz
- **RAM**: 4 GB
- **Network**: 1 Mbps upload/download
- **Webcam**: 480p
- **Microphone**: Any

### Recommended Requirements

- **OS**: Windows 11, macOS 12+, Linux (Ubuntu 22.04+)
- **CPU**: Quad-core 2.5 GHz+
- **RAM**: 8 GB+
- **Network**: 10 Mbps+ upload/download
- **Webcam**: 720p or higher
- **Microphone**: USB or built-in with noise cancellation

## FAQ

**Q: How many participants can join?**
A: Tested with up to 10 participants. Performance depends on network and hardware.

**Q: Is there a mobile app?**
A: Not currently. Desktop only (Windows, macOS, Linux).

**Q: Can I record sessions?**
A: Not built-in. Use external screen recording software.

**Q: Is it secure?**
A: Designed for trusted local networks. No end-to-end encryption currently.

**Q: Can I use it over the internet?**
A: Possible with port forwarding or VPN, but designed for LAN use.

**Q: What codecs are used?**
A: Opus for audio, JPEG for video/screen sharing.

**Q: Can I customize the UI?**
A: Yes, modify [`client_gui.py`](client/ui/client_gui.py:1) for customization.

**Q: How do I report bugs?**
A: Check console logs and report issues with details.

## Support

For issues, questions, or contributions:
- Check console output for error messages
- Review this guide thoroughly
- Check system requirements
- Verify all dependencies installed

## License

This project is provided as-is for educational and internal use.

## Version History

- **v1.0.0** - Initial release with complete Zoom-like features
  - Video conferencing
  - Audio communication
  - Screen sharing
  - Text chat
  - File sharing
  - Participant management