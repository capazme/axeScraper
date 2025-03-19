# src/utils/output_manager.py
import os
import shutil
import re
from pathlib import Path
import datetime
import logging
from typing import Dict, Any, Optional, Union, List, Tuple

class OutputManager:
    """
    Centralized manager for all file and directory operations.
    Provides a consistent interface for path management across all components.
    """
    
    def __init__(
        self,
        base_dir: Union[str, Path],
        domain: str,
        timestamp: Optional[str] = None,
        create_dirs: bool = True,
        config: Optional[Dict[str, Any]] = None
    ):
        """Initialize the output manager with domain-specific structure."""
        self.base_dir = Path(base_dir)
        self.domain = domain
        
        # Generate timestamp for this run
        self.timestamp = timestamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
        # Create safe domain slug for directory names
        self.domain_slug = self._create_safe_slug(domain)
        
        # Standard directory structure for all domains
        self.structure = {
            "root": self.base_dir / self.domain_slug,
            "crawler": self.base_dir / self.domain_slug / "crawler_output",
            "axe": self.base_dir / self.domain_slug / "axe_output",
            "analysis": self.base_dir / self.domain_slug / "analysis_output",
            "reports": self.base_dir / self.domain_slug / "reports",
            "logs": self.base_dir / self.domain_slug / "logs",
            "charts": self.base_dir / self.domain_slug / "charts",
            "temp": self.base_dir / self.domain_slug / "temp",
        }
        
        # Apply any configuration overrides
        if config:
            for key, value in config.items():
                if key in self.structure:
                    self.structure[key] = Path(value)
        
        # Setup logger
        self.logger = logging.getLogger("output_manager")
        
        # Create directories if requested
        if create_dirs:
            self.create_directories()
    
    def _create_safe_slug(self, domain: str) -> str:
        """Create filesystem-safe identifier from domain name."""
        # Remove http/https and www
        clean_domain = domain.replace("http://", "").replace("https://", "").replace("www.", "")
        
        # Replace non-alphanumeric characters with underscores
        return "".join(c if c.isalnum() else "_" for c in clean_domain)
    
    def create_directories(self) -> None:
        """Create all output directories in the structure."""
        for component, directory in self.structure.items():
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Created directory for {component}: {directory}")
    
    def get_path(self, component: str, filename: Optional[str] = None) -> Path:
        """Get path for a specific component, optionally with a filename."""
        if component not in self.structure:
            raise ValueError(f"Unknown component: {component}")
            
        path = self.structure[component]
        
        if filename:
            return path / filename
        
        return path
    
    def get_timestamped_path(self, component: str, base_filename: str, ext: str = "") -> Path:
        """Get path with timestamp included in the filename."""
        if not ext.startswith(".") and ext:
            ext = f".{ext}"
            
        filename = f"{base_filename}_{self.timestamp}{ext}"
        return self.get_path(component, filename)
    
    def backup_existing_file(self, component: str, filename: str, max_backups: int = 5) -> Optional[Path]:
        """Backup an existing file if it exists."""
        file_path = self.get_path(component, filename)
        if not file_path.exists():
            return None
            
        # Create backup filename with timestamp
        backup_name = f"{file_path.stem}_backup_{self.timestamp}{file_path.suffix}"
        backup_path = file_path.parent / backup_name
        
        try:
            # Copy the file to create the backup
            shutil.copy2(file_path, backup_path)
            self.logger.info(f"Created backup of {file_path} to {backup_path}")
            
            # Clean up old backups if necessary
            self._cleanup_old_backups(file_path.parent, file_path.stem, file_path.suffix, max_backups)
            
            return backup_path
        except Exception as e:
            self.logger.error(f"Error creating backup of {file_path}: {e}")
            return None
    
    def _cleanup_old_backups(self, directory: Path, base_name: str, extension: str, max_backups: int) -> None:
        """Remove old backup files, keeping only the most recent ones."""
        # Pattern for backup files
        pattern = f"{base_name}_backup_*{extension}"
        
        # Get all backup files sorted by modification time (newest first)
        backup_files = sorted(
            directory.glob(pattern),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        # Remove oldest backups beyond the limit
        if len(backup_files) > max_backups:
            for old_backup in backup_files[max_backups:]:
                try:
                    old_backup.unlink()
                    self.logger.debug(f"Removed old backup: {old_backup}")
                except Exception as e:
                    self.logger.warning(f"Error removing old backup {old_backup}: {e}")
    
    def safe_write_file(self, component: str, filename: str, content: str, 
                        encoding: str = "utf-8", backup: bool = True) -> Path:
        """Write content to a file safely, creating a backup first."""
        path = self.get_path(component, filename)
        
        # Create backup if needed
        if backup and path.exists():
            self.backup_existing_file(component, filename)
        
        # Write to temporary file first
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(content, encoding=encoding)
        
        # Replace the original file with the temporary file
        temp_path.replace(path)
        self.logger.debug(f"Safely wrote content to {path}")
        
        return path
    
    def ensure_path_exists(self, component: str, filename: Optional[str] = None) -> Path:
        """Ensure a path exists, creating any necessary directories."""
        path = self.get_path(component, filename)
        
        if filename:
            # If a filename is included, ensure the parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # If no filename, ensure the directory itself exists
            path.mkdir(parents=True, exist_ok=True)
            
        return path
    
    def find_latest_file(self, component: str, pattern: str) -> Optional[Path]:
        """Find the most recently modified file matching a pattern."""
        directory = self.get_path(component)
        matching_files = list(directory.glob(pattern))
        
        if not matching_files:
            return None
            
        return max(matching_files, key=lambda p: p.stat().st_mtime)