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
    if console_output and not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    
    # Log startup message
    logger.info(f"Logger initialized for {component_name} - level: {log_level}")
    if log_dir:
        logger.info(f"Log file: {log_file_path}")
    
    return logger

def get_logger(component_name: str, log_config: Optional[Dict[str, Any]] = None, 
               output_manager: Optional[Any] = None) -> logging.Logger:
    """
    Get or create a logger with standardized configuration.
    
    Args:
        component_name: Name of the component requesting the logger
        log_config: Optional logging configuration
        output_manager: Optional output manager for path resolution
        
    Returns:
        Configured logger instance
    """
    # Use component_name as a cache key to avoid duplicate loggers
    logger = logging.getLogger(component_name)
    
    # If this logger is already configured, return it
    if logger.handlers:
        return logger
        
    # Prevent propagation to parent loggers to avoid duplication
    logger.propagate = False
    
    try:
        # Only attempt to import if needed
        if not log_config:
            # Import dynamically to avoid circular imports
            from utils.config_manager import get_config_manager
            
            # Get or create configuration manager
            config_manager = get_config_manager()
            if config_manager:
                log_config = config_manager.get_logging_config().get("components", {}).get(component_name, {})
    except ImportError:
        # If import fails, use default config
        pass
        
    # Use default log level if not specified in config
    log_level = log_config.get("level", "INFO") if log_config else "INFO"
    
    # Get log directory from output_manager if provided
    if output_manager:
        log_dir = output_manager.get_path("logs")
        log_file = f"{component_name}.log"
    else:
        log_dir = Path("./logs")
        log_file = f"{component_name}.log"

    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)
    
    # Create file handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    
    # Create console handler
    console_handler = logging.StreamHandler()
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Set formatter for handlers
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Set log level for handlers
    file_handler.setLevel(log_level)
    console_handler.setLevel(log_level)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Set logger level
    logger.setLevel(log_level)
    
    return logger