# src/utils/logging_config.py
import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional, Dict, Any, Union
import sys

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
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        
        if log_file is None:
            log_file = f"{component_name}.log"
            
        log_file_path = log_dir_path / log_file
        
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

def get_logger(
    component_name: str, 
    log_config: Optional[Dict[str, Any]] = None,
    output_manager = None
) -> logging.Logger:
    """Get properly configured logger for a component."""
    # Use component_name as a cache key to avoid creating duplicate loggers
    logger = logging.getLogger(component_name)
    
    # If this logger is already configured, return it
    if logger.handlers:
        return logger
        
    # Otherwise, configure it
    try:
        # Import configuration here to avoid circular imports
        from .config_manager import ConfigurationManager
        config_manager = ConfigurationManager(project_name="axeScraper")
        config = config_manager.get_logging_config()
    except ImportError:
        # Fallback configuration if config_manager can't be imported
        config = {
            "level": "INFO",
            "console_output": True,
            "rotating_logs": True,
            "max_bytes": 10 * 1024 * 1024,
            "backup_count": 5,
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            'datefmt': '%Y-%m-%d %H:%M:%S',
            "components": {}
        }
    
    # Merge with provided config
    if log_config:
        for key, value in log_config.items():
            config[key] = value
    
    # Get log directory from output_manager if provided
    if output_manager:
        log_dir = output_manager.get_path("logs")
        log_file = f"{component_name}.log"
    else:
        log_dir = config.get("log_dir", "./logs")
        # Get component-specific log file if specified
        component_config = config.get("components", {}).get(component_name, {})
        log_file = component_config.get("log_file", f"{component_name}.log")
    
    # Get component-specific log level if available
    log_level = config.get("components", {}).get(component_name, {}).get("level", config.get("level", "INFO"))
    
    # Set up logging with merged configuration
    return setup_logging(
        log_level=log_level,
        log_dir=log_dir,
        log_file=log_file,
        component_name=component_name,
        console_output=config.get("console_output", True),
        rotating_logs=config.get("rotating_logs", True),
        max_bytes=config.get("max_bytes", 10 * 1024 * 1024),
        backup_count=config.get("backup_count", 5),
        log_format=config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        date_format=config.get("date_format", "%Y-%m-%d %H:%M:%S")
    )