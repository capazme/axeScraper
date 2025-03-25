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
            "screenshots": self.base_dir / self.domain_slug / "screenshots",  
            "funnels": self.base_dir / self.domain_slug / "funnels",  
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
        
        # Estrai solo la parte del dominio (senza path)
        clean_domain = clean_domain.split('/')[0]
        
        # Replace non-alphanumeric characters with underscores
        return "".join(c if c.isalnum() else "_" for c in clean_domain)
    
    def create_directories(self) -> None:
        """Create all output directories in the structure."""
        for component, directory in self.structure.items():
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Created directory for {component}: {directory}")
    
    def validate_path(self, path: Path) -> Path:
        """Ensure a path exists and is valid."""
        if path is None:
            raise ValueError("Path cannot be None")
        
        # Ensure parent directory exists
        if not path.is_dir():
            path.parent.mkdir(parents=True, exist_ok=True)
        
        return path
    
    def get_path(self, component: str, *path_elements) -> Path:
        """Get path for a specific component with consistent handling."""
        if component not in self.structure:
            # Ensure logs always go to the same place
            if component == "logs":
                path = self.structure.get("logs", self.base_dir / self.domain_slug / "logs")
            else:
                raise ValueError(f"Unknown component: {component}")
        else:
            path = self.structure[component]
        
        # Handle path elements normally
        valid_elements = [str(element) for element in path_elements if element is not None]
        if valid_elements:
            return path.joinpath(*valid_elements)
        
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
    
    def safe_write_file(self, path: Union[Path, str], content: str, encoding: str = "utf-8") -> bool:
        """
        Safely write content to a file, ensuring the directory exists.
        
        Args:
            path: Path to write to
            content: Content to write
            encoding: File encoding to use
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Convert to Path object if string
            path = Path(path)
            
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write content to file
            path.write_text(content, encoding=encoding)
            self.logger.debug(f"Successfully wrote content to {path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error writing file {path}: {e}")
            return False

    def ensure_path_exists(self, component: str, filename: Optional[str] = None) -> Path:
        """
        Ensure a path exists, creating any necessary directories.
        
        Args:
            component: Component name to get base path
            filename: Optional filename to append
            
        Returns:
            Path that is guaranteed to exist
        """
        if filename is None:
            # If no filename, ensure the directory itself exists
            path = self.get_path(component)
            path.mkdir(parents=True, exist_ok=True)
        else:
            # If a filename is included, ensure the parent directory exists
            path = self.get_path(component, filename)
            path.parent.mkdir(parents=True, exist_ok=True)
                
        return path
    
    def ensure_nested_path_exists(self, component: str, *subpaths) -> Path:
        """
        Ensure a nested path exists, creating all necessary directories.
        
        Args:
            component: Base component name
            *subpaths: Variable number of subdirectory names
            
        Returns:
            Path: Complete path with all directories created
        """
        # Get the base component path
        base_path = self.get_path(component)
        
        # Start with the base path
        current_path = base_path
        
        # Create each level of subdirectory
        for subpath in subpaths:
            if subpath is not None:
                current_path = current_path / str(subpath)
        
        # Ensure all directories exist
        current_path.mkdir(parents=True, exist_ok=True)
        
        return current_path

    def find_latest_file(self, component: str, pattern: str) -> Optional[Path]:
        """Find the most recently modified file matching a pattern."""
        directory = self.get_path(component)
        matching_files = list(directory.glob(pattern))
        
        if not matching_files:
            return None
            
        return max(matching_files, key=lambda p: p.stat().st_mtime)
    
    def get_crawler_state_path(self, domain_suffix: Optional[str] = None) -> Path:
        """
        Ottiene il percorso del file di stato del crawler, controllando più posizioni possibili.
        Implementa una ricerca gerarchica per trovare il file anche se si trova in posizioni alternative.
        
        Args:
            domain_suffix: Eventuale suffisso del dominio per il nome del file
            
        Returns:
            Path al file di stato del crawler trovato o il percorso predefinito se non trovato
        """
        # Estrai il dominio di base dalla URL completa
        basic_domain = self.domain.replace("http://", "").replace("https://", "").replace("www.", "")
        basic_domain = basic_domain.split('/')[0]  # Solo la parte del dominio
        
        # Lista di possibili percorsi da controllare in ordine di priorità
        possible_paths = [
            # Formato standard per il file di stato
            self.get_path("crawler", f"crawler_state_{self.domain_slug}.pkl"),
            
            # Formato alternativo usato dal multi_domain_crawler
            self.get_path("crawler", f"{basic_domain}/crawler_state_{basic_domain}.pkl"),
            
            # Format with domain as subdirectory 
            self.get_path("crawler") / basic_domain / f"crawler_state_{basic_domain}.pkl",
            
            # Usando solo il dominio di base senza slug
            self.get_path("crawler", f"crawler_state_{basic_domain}.pkl"),
            
            # Formato con dominio come slug nella directory principale
            self.get_path("root") / "crawler_output" / f"crawler_state_{self.domain_slug}.pkl",
            
            # Vecchio formato nel percorso root
            self.base_dir / f"crawler_state_{basic_domain}.pkl"
        ]
        
        # Cerca in tutte le posizioni possibili, tornando il primo file trovato
        for path in possible_paths:
            if path.exists():
                self.logger.info(f"Trovato file di stato crawler: {path}")
                return path
        
        # Cerca file che corrispondono a pattern simili in caso di varianti nel nome
        crawler_dir = self.get_path("crawler")
        if crawler_dir.exists():
            for file in crawler_dir.glob("crawler_state_*.pkl"):
                self.logger.info(f"Trovato file di stato crawler alternativo: {file}")
                return file
        
        # Se nessun file esiste, usa il path primario come default
        default_path = possible_paths[0]
        self.logger.warning(f"Nessun file di stato crawler trovato, verrà usato: {default_path}")
        return default_path

    def get_axe_report_path(self) -> Path:
        """
        Ottiene il percorso del report di Axe, verificando possibili varianti.
        
        Returns:
            Path al report di Axe esistente o percorso standard se non trovato
        """
        # Percorso standard
        standard_path = self.get_path("axe", f"accessibility_report_{self.domain_slug}.xlsx")
        
        if standard_path.exists():
            return standard_path
        
        # Cerca varianti del nome del file
        axe_dir = self.get_path("axe")
        if axe_dir.exists():
            # Cerca qualsiasi report di accessibilità
            for file in axe_dir.glob("accessibility_report_*.xlsx"):
                return file
        
        # Restituisci il percorso standard anche se non esiste
        return standard_path