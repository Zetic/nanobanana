import logging
import os
from datetime import datetime
from typing import Optional
import config

class DailyFileHandler(logging.Handler):
    """Custom logging handler that creates daily log files."""
    
    def __init__(self):
        super().__init__()
        self.current_date = None
        self.current_file_handler = None
        self._ensure_logs_dir()
    
    def _ensure_logs_dir(self):
        """Ensure the logs directory exists."""
        os.makedirs(config.LOGS_DIR, exist_ok=True)
    
    def _get_log_filename(self, date: datetime) -> str:
        """Get the log filename for a specific date."""
        date_str = date.strftime('%Y-%m-%d')
        return os.path.join(config.LOGS_DIR, f'bot-{date_str}.log')
    
    def _get_current_log_file(self) -> str:
        """Get the current log file path."""
        now = datetime.now()
        return self._get_log_filename(now)
    
    def _rotate_if_needed(self):
        """Rotate to a new log file if the date has changed."""
        now = datetime.now()
        current_date = now.date()
        
        if self.current_date != current_date:
            # Close the current file handler if it exists
            if self.current_file_handler:
                self.current_file_handler.close()
            
            # Create new file handler for the current date
            log_filename = self._get_log_filename(now)
            self.current_file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
            self.current_file_handler.setFormatter(self.formatter)
            self.current_date = current_date
    
    def emit(self, record):
        """Emit a log record to the appropriate daily log file."""
        try:
            self._rotate_if_needed()
            if self.current_file_handler:
                self.current_file_handler.emit(record)
        except Exception:
            self.handleError(record)

class LogManager:
    """Manages daily log files for the bot."""
    
    def __init__(self):
        self.daily_handler = None
        self._setup_daily_logging()
    
    def _setup_daily_logging(self):
        """Set up daily file logging."""
        # Create and configure the daily file handler
        self.daily_handler = DailyFileHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.daily_handler.setFormatter(formatter)
        
        # Add the handler to the root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self.daily_handler)
    
    def get_current_log_file(self) -> Optional[str]:
        """Get the path to the current day's log file."""
        if self.daily_handler:
            return self.daily_handler._get_current_log_file()
        return None
    
    def get_most_recent_log_file(self) -> Optional[str]:
        """Get the path to the most recent log file."""
        try:
            # List all log files in the logs directory
            log_files = []
            for filename in os.listdir(config.LOGS_DIR):
                if filename.startswith('bot-') and filename.endswith('.log'):
                    filepath = os.path.join(config.LOGS_DIR, filename)
                    if os.path.isfile(filepath):
                        log_files.append(filepath)
            
            if not log_files:
                return None
            
            # Sort by modification time (most recent first)
            log_files.sort(key=os.path.getmtime, reverse=True)
            return log_files[0]
            
        except Exception:
            return None
    
    def set_debug_logging(self, enabled: bool = True) -> None:
        """
        Enable or disable debug logging for voice handler troubleshooting.
        
        When enabled, detailed timing information and voice pipeline events
        will be logged to help diagnose slow response times.
        
        Args:
            enabled: True to enable DEBUG level logging, False to set INFO level
        """
        level = logging.DEBUG if enabled else logging.INFO
        
        # Set level for voice handler module specifically
        voice_logger = logging.getLogger('voice_handler')
        voice_logger.setLevel(level)
        
        # Also set the root logger level if enabling debug
        root_logger = logging.getLogger()
        if enabled:
            root_logger.setLevel(logging.DEBUG)
        else:
            root_logger.setLevel(logging.INFO)
        
        # Set level on the daily handler
        if self.daily_handler:
            self.daily_handler.setLevel(level)
        
        status = "enabled" if enabled else "disabled"
        logging.info(f"Debug logging {status}")

# Global instance
log_manager = LogManager()