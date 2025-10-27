#!/usr/bin/env python3
"""
Unit tests for file links cleanup in client_gui.py

Tests the memory leak fix for _file_links in ChatWidget:
- Immediate cleanup after download
- TTL-based periodic pruning
- LRU eviction at max capacity
- Graceful handling of missing entries
"""

import unittest
import time
from unittest.mock import Mock, patch

# Import the ChatWidget from client.ui.client_gui
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from client.ui.client_gui import ChatWidget


class TestFileLinksCleanup(unittest.TestCase):
    """Test cases for file links cleanup functionality."""
    
    @classmethod
    def setUpClass(cls):
        """Create QApplication once for all tests."""
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()
    
    def setUp(self):
        """Set up test fixtures."""
        self.chat_widget = ChatWidget()
        # Shorter TTL for testing
        self.chat_widget._file_links_ttl_seconds = 1  # 1 second for testing
        self.chat_widget._file_links_max_size = 5  # Small max size for testing
    
    def test_immediate_cleanup_after_download(self):
        """Test that file link is removed immediately after download request."""
        fid = "test_file_123"
        filename = "test_file.txt"
        size_display = "1.0 KB"
        
        # Add a file notification
        self.chat_widget.add_file_notification(
            "Test notification", fid, filename, size_display
        )
        
        # Verify file link was stored
        self.assertIn(fid, self.chat_widget._file_links)
        
        # Simulate anchor click (download)
        from PyQt6.QtCore import QUrl
        url = QUrl(f"download://{fid}")
        
        with patch.object(self.chat_widget, 'file_download_requested') as mock_signal:
            self.chat_widget._on_anchor_clicked(url)
            
            # Verify signal was emitted
            mock_signal.emit.assert_called_once_with(fid, filename)
        
        # Verify file link was removed immediately
        self.assertNotIn(fid, self.chat_widget._file_links)
    
    def test_missing_entry_handling(self):
        """Test that missing entries are handled gracefully."""
        fid = "nonexistent_file"
        
        # Try to access a non-existent file link
        from PyQt6.QtCore import QUrl
        url = QUrl(f"download://{fid}")
        
        with patch.object(self.chat_widget, 'add_message') as mock_add:
            self.chat_widget._on_anchor_clicked(url)
            
            # Verify appropriate message was added
            mock_add.assert_called_once()
            call_args = mock_add.call_args
            # Check first argument (username)
            self.assertEqual(call_args[0][0], "System")
            # Check if is_system was passed (could be positional or keyword)
            if len(call_args[0]) >= 3:
                self.assertEqual(call_args[0][2], True)
            elif 'is_system' in call_args[1]:
                self.assertEqual(call_args[1]['is_system'], True)
    
    def test_ttl_expiration_pruning(self):
        """Test that old entries are pruned based on TTL."""
        # Add file links with different timestamps
        current_time = time.time()
        
        # Add expired entry
        fid1 = "expired_file"
        self.chat_widget._file_links[fid1] = {
            'filename': 'expired.txt',
            'size': '1 KB',
            'timestamp': current_time - 2  # 2 seconds ago (expired)
        }
        
        # Add non-expired entry
        fid2 = "current_file"
        self.chat_widget._file_links[fid2] = {
            'filename': 'current.txt',
            'size': '1 KB',
            'timestamp': current_time  # Now
        }
        
        # Run prune
        self.chat_widget._prune_file_links()
        
        # Verify expired entry was removed
        self.assertNotIn(fid1, self.chat_widget._file_links)
        
        # Verify current entry was kept
        self.assertIn(fid2, self.chat_widget._file_links)
    
    def test_lru_eviction_at_max_capacity(self):
        """Test that oldest entry is evicted when max capacity is reached."""
        # Add entries up to max size
        for i in range(self.chat_widget._file_links_max_size):
            fid = f"file_{i}"
            self.chat_widget._file_links[fid] = {
                'filename': f'file_{i}.txt',
                'size': '1 KB',
                'timestamp': time.time() - i  # Different timestamps
            }
        
        # Verify at max capacity
        self.assertEqual(len(self.chat_widget._file_links), 
                        self.chat_widget._file_links_max_size)
        
        # Get the oldest fid (should be the last one added with i=4)
        oldest_fid = f"file_{self.chat_widget._file_links_max_size - 1}"
        
        # Add one more entry (should trigger eviction)
        new_fid = "new_file"
        self.chat_widget.add_file_notification(
            "Test", new_fid, "new.txt", "1 KB"
        )
        
        # Verify oldest entry was evicted
        self.assertNotIn(oldest_fid, self.chat_widget._file_links)
        
        # Verify new entry was added
        self.assertIn(new_fid, self.chat_widget._file_links)
        
        # Verify still at max capacity
        self.assertEqual(len(self.chat_widget._file_links), 
                        self.chat_widget._file_links_max_size)
    
    def test_timestamp_stored_on_notification(self):
        """Test that timestamp is stored when adding file notification."""
        fid = "test_file"
        filename = "test.txt"
        size_display = "1.0 KB"
        
        # Add file notification
        self.chat_widget.add_file_notification(
            "Test", fid, filename, size_display
        )
        
        # Verify entry exists with timestamp
        self.assertIn(fid, self.chat_widget._file_links)
        entry = self.chat_widget._file_links[fid]
        self.assertIn('timestamp', entry)
        self.assertIsInstance(entry['timestamp'], float)
        # Timestamp should be very recent (within last second)
        self.assertAlmostEqual(entry['timestamp'], time.time(), delta=1.0)
    
    def test_multiple_downloads_cleanup(self):
        """Test that multiple downloads properly clean up their links."""
        fids = ["file1", "file2", "file3"]
        
        # Add multiple file notifications
        for fid in fids:
            self.chat_widget.add_file_notification(
                "Test", fid, f"{fid}.txt", "1 KB"
            )
        
        # Verify all were stored
        for fid in fids:
            self.assertIn(fid, self.chat_widget._file_links)
        
        # Simulate downloads
        from PyQt6.QtCore import QUrl
        for fid in fids:
            url = QUrl(f"download://{fid}")
            with patch.object(self.chat_widget, 'file_download_requested'):
                self.chat_widget._on_anchor_clicked(url)
        
        # Verify all were cleaned up
        for fid in fids:
            self.assertNotIn(fid, self.chat_widget._file_links)
    
    def test_empty_cleanup_with_no_expired_entries(self):
        """Test that pruning with no expired entries doesn't break."""
        # Add non-expired entry
        fid = "current_file"
        self.chat_widget._file_links[fid] = {
            'filename': 'current.txt',
            'size': '1 KB',
            'timestamp': time.time()
        }
        
        initial_count = len(self.chat_widget._file_links)
        
        # Run prune (should not remove anything)
        self.chat_widget._prune_file_links()
        
        # Verify nothing was removed
        self.assertEqual(len(self.chat_widget._file_links), initial_count)
        self.assertIn(fid, self.chat_widget._file_links)
    
    def test_eviction_with_empty_dict(self):
        """Test that eviction works correctly with empty dictionary."""
        # Should not raise exception
        self.chat_widget._evict_lru_file_link()
        
        # Should still work fine
        self.assertEqual(len(self.chat_widget._file_links), 0)
    
    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, 'chat_widget'):
            # Clean up timer if exists
            if hasattr(self.chat_widget, '_file_links_cleanup_timer'):
                self.chat_widget._file_links_cleanup_timer.stop()
            self.chat_widget.deleteLater()


if __name__ == '__main__':
    unittest.main()

