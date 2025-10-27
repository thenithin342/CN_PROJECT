# LAN Collaboration System - Deployment & Testing Guide

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Server Deployment](#server-deployment)
3. [Client Deployment](#client-deployment)
4. [Testing Procedures](#testing-procedures)
5. [Performance Benchmarks](#performance-benchmarks)
6. [Troubleshooting](#troubleshooting)
7. [Monitoring](#monitoring)

## Pre-Deployment Checklist

### System Requirements Verification

```bash
# Check Python version (3.8+)
python --version

# Check pip
pip --version

# Check available ports
netstat -an | grep -E "9000|10000|11000"

# Check disk space (minimum 1GB for uploads)
df -h

# Check network connectivity
ping 192.168.1.1
```

### Dependency Installation

```bash
# Install all dependencies
pip install -r requirements.txt

# Verify installation
python main_app.py --check-deps

# Expected output: "All dependencies are installed!"
```

### Network Configuration

1. **Firewall Rules**:
   ```bash
   # Linux (ufw)
   sudo ufw allow 9000/tcp
   sudo ufw allow 10000/udp
   sudo ufw allow 11000/udp
   
   # Windows (PowerShell as Admin)
   New-NetFirewallRule -DisplayName "LAN Collab TCP" -Direction Inbound -Protocol TCP -LocalPort 9000 -Action Allow
   New-NetFirewallRule -DisplayName "LAN Collab Video" -Direction Inbound -Protocol UDP -LocalPort 10000 -Action Allow
   New-NetFirewallRule -DisplayName "LAN Collab Audio" -Direction Inbound -Protocol UDP -LocalPort 11000 -Action Allow
   ```

2. **Port Availability**:
   ```bash
   # Check if ports are free
   lsof -i :9000
   lsof -i :10000
   lsof -i :11000
   ```

## Server Deployment

### Basic Deployment

```bash
# Start server with default settings
python server/main_server.py

# Expected output:
# [INFO] Audio server initialized
# [INFO] Video server initialized
# [INFO] Server listening on ('0.0.0.0', 9000)
```

### Production Deployment

```bash
# Create uploads directory
mkdir -p uploads
chmod 755 uploads

# Start server with logging
python server/main_server.py \
  --host 0.0.0.0 \
  --port 9000 \
  --audio-port 11000 \
  --video-port 10000 \
  --upload-dir ./uploads \
  2>&1 | tee server.log
```

### Systemd Service (Linux)

Create `/etc/systemd/system/lan-collab.service`:

```ini
[Unit]
Description=LAN Collaboration Server
After=network.target

[Service]
Type=simple
User=lancollab
WorkingDirectory=/opt/lan-collab
ExecStart=/usr/bin/python3 /opt/lan-collab/server/main_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable lan-collab
sudo systemctl start lan-collab
sudo systemctl status lan-collab
```

### Docker Deployment

Create `Dockerfile`:

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9000/tcp 10000/udp 11000/udp

CMD ["python", "server/main_server.py", "--host", "0.0.0.0"]
```

Build and run:
```bash
docker build -t lan-collab-server .
docker run -d \
  -p 9000:9000/tcp \
  -p 10000:10000/udp \
  -p 11000:11000/udp \
  -v $(pwd)/uploads:/app/uploads \
  --name lan-collab \
  lan-collab-server
```

## Client Deployment

### Desktop Application

```bash
# Run directly
python main_app.py --server SERVER_IP

# With custom settings
python main_app.py \
  --server 192.168.1.100 \
  --port 9000 \
  --audio-port 11000 \
  --video-port 10000 \
  --username "John Doe"
```

### Executable Creation

```bash
# Install PyInstaller
pip install pyinstaller

# Create executable (Windows)
pyinstaller --onefile --windowed \
  --name "LAN-Collaboration" \
  --icon=icon.ico \
  main_app.py

# Create executable (macOS)
pyinstaller --onefile --windowed \
  --name "LAN Collaboration" \
  --icon=icon.icns \
  main_app.py

# Create executable (Linux)
pyinstaller --onefile \
  --name "lan-collaboration" \
  main_app.py
```

## Testing Procedures

### Unit Tests

Create `tests/test_integration.py`:

```python
import pytest
import asyncio
from server.main_server import CollaborationServer
from client.main_client import CollaborationClient

@pytest.mark.asyncio
async def test_server_startup():
    """Test server starts successfully."""
    server = CollaborationServer(host='127.0.0.1', port=9999)
    # Test implementation
    assert server is not None

@pytest.mark.asyncio
async def test_client_connection():
    """Test client connects to server."""
    client = CollaborationClient(host='127.0.0.1', port=9999, username='test')
    # Test implementation
    assert client is not None
```

Run tests:
```bash
pytest tests/ -v
```

### Integration Testing

#### Test 1: Server Startup

```bash
# Terminal 1: Start server
python server/main_server.py

# Expected: Server starts without errors
# Check: All three servers (main, audio, video) initialize
```

#### Test 2: Single Client Connection

```bash
# Terminal 2: Start client
python main_app.py

# Expected: 
# - Login dialog appears
# - Connection successful
# - Participant list shows user
```

#### Test 3: Multiple Clients

```bash
# Terminal 2: Client 1
python main_app.py --username "User1"

# Terminal 3: Client 2
python main_app.py --username "User2"

# Terminal 4: Client 3
python main_app.py --username "User3"

# Expected:
# - All clients connect
# - Participant lists update
# - User joined notifications appear
```

#### Test 4: Text Chat

```bash
# In Client 1: Send message "Hello"
# Expected: All clients receive message

# In Client 2: Send broadcast "Broadcast test"
# Expected: All clients see [BROADCAST] message

# In Client 3: Send private message to Client 1
# Expected: Only Client 1 receives message
```

#### Test 5: File Sharing

```bash
# In Client 1: Upload test file (< 100MB)
# Expected:
# - Upload progress shown
# - All clients notified
# - Download link appears

# In Client 2: Click download link
# Expected:
# - Save dialog appears
# - Download completes
# - File matches original
```

#### Test 6: Audio Communication

```bash
# In Client 1: Click "Unmute Audio"
# Expected:
# - Microphone captures audio
# - Audio sent to server
# - Other clients hear audio

# In Client 2: Click "Unmute Audio"
# Expected:
# - Both audio streams mixed
# - All clients hear mixed audio

# In Client 3: Mute Client 1
# Expected:
# - Client 3 doesn't hear Client 1
# - Client 1 still heard by others
```

#### Test 7: Video Communication

```bash
# In Client 1: Click "Start Video"
# Expected:
# - Webcam activates
# - Video feed appears in grid
# - Other clients see video

# In Client 2: Click "Start Video"
# Expected:
# - Both video feeds visible
# - Grid layout adjusts
# - Frame rate stable
```

#### Test 8: Screen Sharing

```bash
# In Client 1: Click "Start Screen Share"
# Expected:
# - Screen capture starts
# - Other clients notified

# In Client 2: Accept view invitation
# Expected:
# - Screen viewer window opens
# - Client 1's screen visible
# - Updates in real-time

# In Client 1: Click "Stop Screen Share"
# Expected:
# - Sharing stops
# - Viewer windows close
```

### Load Testing

#### Test 9: Multiple Simultaneous Users

```bash
# Start 10 clients simultaneously
for i in {1..10}; do
  python main_app.py --username "User$i" &
done

# Monitor:
# - Server CPU usage
# - Network bandwidth
# - Memory consumption
# - Response times
```

#### Test 10: Stress Test

```bash
# All clients:
# - Enable video
# - Enable audio
# - Send messages
# - Share files

# Monitor:
# - Frame drops
# - Audio quality
# - Message latency
# - File transfer speed
```

### Edge Case Testing

#### Test 11: Network Interruption

```bash
# Disconnect client network
# Expected:
# - Reconnection attempts
# - Graceful degradation
# - Error messages

# Reconnect network
# Expected:
# - Automatic reconnection
# - State restoration
```

#### Test 12: Server Restart

```bash
# Stop server while clients connected
# Expected:
# - Clients detect disconnection
# - Error messages shown

# Restart server
# Expected:
# - Clients can reconnect
# - New session starts
```

#### Test 13: Resource Limits

```bash
# Upload 100MB file (max size)
# Expected: Success

# Upload 101MB file
# Expected: Error message

# Fill server disk
# Expected: Upload fails gracefully
```

## Performance Benchmarks

### Expected Performance Metrics

| Metric | Target | Acceptable | Poor |
|--------|--------|------------|------|
| Video Latency | < 200ms | < 500ms | > 500ms |
| Audio Latency | < 100ms | < 200ms | > 200ms |
| Message Latency | < 50ms | < 100ms | > 100ms |
| File Transfer | > 10 MB/s | > 5 MB/s | < 5 MB/s |
| CPU Usage (Server) | < 30% | < 50% | > 50% |
| Memory Usage | < 500MB | < 1GB | > 1GB |
| Concurrent Users | 10+ | 5-10 | < 5 |

### Benchmarking Tools

```bash
# Network latency
ping SERVER_IP

# Bandwidth
iperf3 -c SERVER_IP

# CPU/Memory monitoring
top -p $(pgrep -f main_server.py)

# Network traffic
iftop -i eth0
```

## Troubleshooting

### Common Issues

#### Issue: Server won't start

**Symptoms**: Error on startup, port binding fails

**Solutions**:
```bash
# Check port availability
netstat -tulpn | grep -E "9000|10000|11000"

# Kill conflicting processes
kill $(lsof -t -i:9000)

# Use different ports
python server/main_server.py --port 9001
```

#### Issue: Client can't connect

**Symptoms**: Connection timeout, refused connection

**Solutions**:
```bash
# Verify server running
ps aux | grep main_server

# Check firewall
sudo ufw status

# Test connectivity
telnet SERVER_IP 9000
```

#### Issue: No audio

**Symptoms**: Audio not transmitting or receiving

**Solutions**:
```bash
# Check audio devices
python -c "import sounddevice; print(sounddevice.query_devices())"

# Verify opuslib
python -c "import opuslib; print('OK')"

# Check permissions (macOS)
# System Preferences > Security & Privacy > Microphone
```

#### Issue: No video

**Symptoms**: Video feed not appearing

**Solutions**:
```bash
# Check webcam
python -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened())"

# Verify opencv
python -c "import cv2; print(cv2.__version__)"

# Check permissions (macOS)
# System Preferences > Security & Privacy > Camera
```

## Monitoring

### Server Monitoring

Create `monitor_server.sh`:

```bash
#!/bin/bash

while true; do
  echo "=== $(date) ==="
  
  # Process status
  ps aux | grep main_server.py | grep -v grep
  
  # Port status
  netstat -tulpn | grep -E "9000|10000|11000"
  
  # Resource usage
  top -b -n 1 | grep python
  
  # Disk space
  df -h | grep -E "/$|uploads"
  
  # Network connections
  netstat -an | grep -E "9000|10000|11000" | wc -l
  
  echo ""
  sleep 60
done
```

### Log Analysis

```bash
# Monitor server logs
tail -f server.log

# Filter errors
grep ERROR server.log

# Count connections
grep "New client connected" server.log | wc -l

# Analyze performance
grep "Frame" server.log | tail -100
```

### Health Checks

Create `health_check.py`:

```python
#!/usr/bin/env python3
import socket
import sys

def check_port(host, port, protocol='tcp'):
    """Check if port is open."""
    try:
        if protocol == 'tcp':
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        else:  # UDP
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            sock.sendto(b'', (host, port))
            sock.close()
            return True
    except:
        return False

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    
    checks = [
        ('TCP 9000', host, 9000, 'tcp'),
        ('UDP 10000', host, 10000, 'udp'),
        ('UDP 11000', host, 11000, 'udp'),
    ]
    
    all_ok = True
    for name, h, p, proto in checks:
        status = check_port(h, p, proto)
        print(f"{name}: {'✓ OK' if status else '✗ FAIL'}")
        if not status:
            all_ok = False
    
    sys.exit(0 if all_ok else 1)

if __name__ == '__main__':
    main()
```

Run health check:
```bash
python health_check.py SERVER_IP
```

## Deployment Checklist

- [ ] System requirements verified
- [ ] Dependencies installed
- [ ] Ports configured in firewall
- [ ] Server starts successfully
- [ ] Client connects successfully
- [ ] Text chat works
- [ ] File sharing works
- [ ] Audio works
- [ ] Video works
- [ ] Screen sharing works
- [ ] Multiple clients tested
- [ ] Load testing completed
- [ ] Edge cases tested
- [ ] Monitoring configured
- [ ] Documentation reviewed
- [ ] Backup procedures established

## Backup and Recovery

### Backup Procedures

```bash
# Backup uploads directory
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz uploads/

# Backup configuration
cp server/utils/config.py config_backup.py

# Backup logs
cp server.log server_backup_$(date +%Y%m%d).log
```

### Recovery Procedures

```bash
# Restore uploads
tar -xzf uploads_backup_YYYYMMDD.tar.gz

# Restore configuration
cp config_backup.py server/utils/config.py

# Restart server
systemctl restart lan-collab
```

## Conclusion

This deployment guide covers all aspects of deploying and testing the LAN Collaboration System. Follow the procedures systematically to ensure a successful deployment.

For additional support, refer to the [User Guide](USER_GUIDE.md) and check console logs for detailed error messages.