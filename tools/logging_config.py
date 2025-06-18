# src/utils/logging_config.py
import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional, Dict, Any, Union
import sys
from src.utils.output_manager import OutputManager

def setup_logging(
    log_level: str = "INFO",
    log_dir: Union[str, Path] = "./logs",
    log_file: Optional[str] = None,
    component_name: str = "axescraper",
    console_output: bool = True,
    rotating_logs: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    date_format: str = "%Y-%m-%d %H:%M:%S",
) -> logging.Logger:
    """Set up standardized logging with consistent configuration."""
    # Convert string log level to logging level
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
        
    # Create logger
    logger = logging.getLogger(component_name)
    
    # Clear any existing handlers to prevent duplicates
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Set the level
    logger.setLevel(numeric_level)
    logger.propagate = False  # Prevent propagation to avoid duplicates
    
    # Create formatter
    formatter = logging.Formatter(log_format, date_format)
    
    # Add file handler if log_dir is specified
    if log_dir:
        try:
            # Convert to Path and ensure directory exists
            log_dir_path = Path(log_dir)
            log_dir_path.mkdir(parents=True, exist_ok=True)
            
            if log_file is None:
                log_file = f"{component_name}.log"
                
            log_file_path = log_dir_path / log_file
            
            print(f"Setting up log file for {component_name} at: {log_file_path}")
            
            if rotating_logs:
                file_handler = logging.handlers.RotatingFileHandler(
                    log_file_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count
                )
            else:
                file_handler = logging.FileHandler(log_file_path)
                
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            print(f"Successfully added file handler for {component_name}")
        except Exception as e:
            print(f"Error setting up log file for {component_name}: {e}")
            # Continue with console logging even if file logging fails
    
    # Add console handler if requested
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # Log startup message
    logger.info(f"Logger initialized for {component_name} - level: {log_level}")
    if log_dir:
        logger.info(f"Log file: {log_file_path}")
    
    return logger

def get_logger(component_name, log_config=None, output_manager=None):
    """Get properly configured logger with file output."""
    # Use component_name as a cache key to avoid duplicate loggers
    logger = logging.getLogger(component_name)
    
    # If this logger is already configured, return it
    if logger.handlers:
        return logger
        
    # Prevent propagation to parent loggers to avoid duplication
    logger.propagate = False
    
    # Default log configuration
    log_level = "INFO"
    log_file = f"{component_name}.log"
    
    # Get component-specific configuration if available
    if log_config:
        log_level = log_config.get("level", log_level)
        log_file = log_config.get("log_file", log_file)
    
    # Determine log directory - create it explicitly
    log_dir = "./logs"  # Default fallback
    
    if output_manager:
        try:
            # Explicitly ensure log directory exists
            log_dir = output_manager.ensure_log_path_exists(component_name)
            print(f"Using output_manager log path for {component_name}: {log_dir}")
        except Exception as e:
            print(f"Error getting log path from output_manager: {e}")
    
    # Set up logging with explicit path creation
    return setup_logging(
        log_level=log_level,
        log_dir=log_dir,
        log_file=log_file,
        component_name=component_name,
        console_output=True,
        rotating_logs=True
    )