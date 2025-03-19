# src/utils/config_manager.py
import os
import json
import yaml
import multiprocessing
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, TypeVar, Set, Callable
import logging

from .env_loader import EnvLoader

# Type variable for generic functions
T = TypeVar('T')

class ConfigurationManager:
    """
    Centralized configuration manager that integrates multiple sources:
    - Command-line arguments (highest priority)
    - Environment variables
    - .env file
    - Configuration files (.json, .yaml, etc.)
    - Default values (lowest priority)
    """
    
    def __init__(
        self,
        project_name: str = "axeScraper",
        env_file: Optional[Union[str, Path]] = None,
        config_file: Optional[Union[str, Path]] = None,
        cli_args: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the configuration manager.
        
        Args:
            project_name: Name of the project
            env_file: Path to .env file
            config_file: Path to configuration file
            cli_args: Command-line arguments
        """
        self.project_name = project_name
        self.env_file = env_file
        self.config_file = config_file
        self.cli_args = cli_args or {}
        
        # Initialize logger
        self.logger = logging.getLogger(f"{project_name}.config")
        
        # Initialize environment loader
        self.env_loader = EnvLoader(env_file)
        
        # Load configuration from env file
        self.env_loader.load()
        
        # Configuration cache
        self._config_cache = {}
        
        # Load configuration from file if specified
        self._file_config = self._load_config_file()
        
        # System resource information
        self.cpu_count = multiprocessing.cpu_count()
        
    def _load_config_file(self) -> Dict[str, Any]:
        """
        Load configuration from a file.
        
        Returns:
            Configuration dictionary
        """
        if not self.config_file:
            # Check environment variable for config file
            config_file_env = self.env_loader.get("AXE_CONFIG_FILE")
            if config_file_env:
                self.config_file = Path(config_file_env)
        
        if not self.config_file or not Path(self.config_file).exists():
            return {}
            
        config_path = Path(self.config_file)
        
        try:
            with open(config_path, 'r') as f:
                if config_path.suffix.lower() == '.json':
                    return json.load(f)
                elif config_path.suffix.lower() in ('.yaml', '.yml'):
                    return yaml.safe_load(f)
                else:
                    # Try to parse as a simple key=value file
                    config = {}
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip()
                    return config
        except Exception as e:
            self.logger.error(f"Error loading configuration file {config_path}: {e}")
            return {}
    
    def get(
        self, 
        key: str, 
        default: Optional[T] = None,
        transform: Optional[Callable[[Any], T]] = None
    ) -> T:
        """
        Get a configuration value with priority handling.
        
        Args:
            key: Configuration key
            default: Default value if not found
            transform: Optional function to transform the value
            
        Returns:
            Configuration value
        """
        # Check cache first
        if key in self._config_cache:
            return self._config_cache[key]
            
        # Priority order:
        # 1. Command-line arguments
        # 2. Environment variables
        # 3. Configuration file
        # 4. Default value
        
        # Command-line arguments have highest priority
        if key in self.cli_args:
            value = self.cli_args[key]
        else:
            # Environment variables (with prefix)
            env_key = f"AXE_{key.upper()}"
            value = self.env_loader.get(env_key)
            
            # If not found in environment, check config file
            if value is None:
                # Support nested keys with dot notation
                if '.' in key:
                    parts = key.split('.')
                    config = self._file_config
                    for part in parts:
                        if not isinstance(config, dict) or part not in config:
                            config = None
                            break
                        config = config[part]
                    value = config
                else:
                    value = self._file_config.get(key)
                
                # If still not found, use default
                if value is None:
                    value = default
        
        # Apply transformation if provided
        if transform and value is not None:
            try:
                value = transform(value)
            except Exception as e:
                self.logger.warning(f"Error transforming value for {key}: {e}")
                value = default
        
        # Cache the result
        self._config_cache[key] = value
        
        return value
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        Get a boolean configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            Boolean configuration value
        """
        return self.get(key, default, lambda v: self._to_bool(v, default))
    
    def _to_bool(self, value: Any, default: bool) -> bool:
        """Convert a value to boolean."""
        if isinstance(value, bool):
            return value
            
        if isinstance(value, str):
            value = value.lower()
            if value in ('1', 'true', 'yes', 'y', 'on'):
                return True
            if value in ('0', 'false', 'no', 'n', 'off'):
                return False
                
        return default
    
    def get_int(self, key: str, default: int = 0) -> int:
        """
        Get an integer configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            Integer configuration value
        """
        return self.get(key, default, lambda v: int(v))
    
    def get_float(self, key: str, default: float = 0.0) -> float:
        """
        Get a float configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            Float configuration value
        """
        return self.get(key, default, lambda v: float(v))
    
    def get_list(
        self, 
        key: str, 
        default: Optional[List[str]] = None,
        separator: str = ','
    ) -> List[str]:
        """
        Get a list configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found
            separator: Separator to split the string into a list
            
        Returns:
            List configuration value
        """
        if default is None:
            default = []
            
        return self.get(key, default, lambda v: self._to_list(v, separator, default))
    
    def _to_list(self, value: Any, separator: str, default: List[str]) -> List[str]:
        """Convert a value to a list."""
        if isinstance(value, list):
            return value
            
        if isinstance(value, str):
            return [item.strip() for item in value.split(separator) if item.strip()]
            
        return default
    
    def get_path(
        self, 
        key: str, 
        default: Optional[Union[str, Path]] = None,
        create: bool = False
    ) -> Path:
        """
        Get a path configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found
            create: Whether to create the directory if it doesn't exist
            
        Returns:
            Path configuration value
        """
        path = self.get(key, default, lambda v: Path(str(v)).expanduser())
        
        if create and path:
            os.makedirs(path, exist_ok=True)
            
        return path
    
    def get_nested(self, key_path: str, default: Optional[T] = None) -> T:
        """
        Get a nested configuration value using dot notation.
        
        Args:
            key_path: Nested key path (e.g., "crawler.max_urls")
            default: Default value if not found
            
        Returns:
            Nested configuration value
        """
        return self.get(key_path, default)
    
    def load_domain_config(self, domain: str) -> Dict[str, Any]:
        """
        Load configuration specific to a domain.
        
        Args:
            domain: Domain name
            
        Returns:
            Domain-specific configuration
        """
        # Get domain slug for consistent reference
        domain_slug = self.domain_to_slug(domain)
        
        # Get base URLs
        base_urls = self.get_list("BASE_URLS")
        
        # Domain output directories
        output_root = self.get_path("OUTPUT_DIR", "~/axeScraper/output", create=True)
        domain_root = output_root / domain_slug
        
        # Standard directory structure
        output_dirs = {
            "root": domain_root,
            "crawler": domain_root / "crawler_output",
            "axe": domain_root / "axe_output",
            "analysis": domain_root / "analysis_output",
            "reports": domain_root / "reports",
            "logs": domain_root / "logs",
            "charts": domain_root / "charts",
            "temp": domain_root / "temp"
        }
        
        # Create directories if needed
        if self.get_bool("CREATE_DIRS", True):
            for dir_path in output_dirs.values():
                os.makedirs(dir_path, exist_ok=True)
        
        # Extract domain without www. prefix
        clean_domain = domain.replace("http://", "").replace("https://", "").replace("www.", "")
        
        # Crawler configuration
        crawler_config = {
            "domains": clean_domain,
            "max_urls": self.get_int("CRAWLER_MAX_URLS", 500),
            "max_retries": self.get_int("CRAWLER_MAX_RETRIES", 10),
            "request_delay": self.get_float("CRAWLER_REQUEST_DELAY", 0.25),
            "hybrid_mode": self.get_bool("CRAWLER_HYBRID_MODE", True),
            "pending_threshold": self.get_int("CRAWLER_PENDING_THRESHOLD", 250),
            "max_workers": self.get_int("CRAWLER_MAX_WORKERS", min(self.cpu_count * 2, 16)),
            "output_dir": str(output_dirs["crawler"]),
            "state_file": str(output_dirs["crawler"] / f"crawler_state_{domain_slug}.pkl"),
        }
        
        # Axe analysis configuration
        axe_config = {
            "domains": clean_domain,
            "max_templates_per_domain": self.get_int("MAX_TEMPLATES", 50),
            "pool_size": self.get_int("POOL_SIZE", 5),
            "sleep_time": self.get_float("SLEEP_TIME", 1),
            "headless": self.get_bool("HEADLESS", True),
            "resume": self.get_bool("RESUME", True),
            "excel_filename": str(output_dirs["axe"] / f"accessibility_report_{domain_slug}.xlsx"),
            "visited_file": str(output_dirs["axe"] / f"visited_urls_{domain_slug}.txt"),
            "output_folder": str(output_dirs["axe"]),
        }
        
        # Final report configuration
        report_config = {
            "input_excel": str(output_dirs["axe"] / f"accessibility_report_{domain_slug}.xlsx"),
            "output_excel": str(output_dirs["analysis"] / f"final_analysis_{domain_slug}.xlsx"),
            "crawler_state": str(output_dirs["crawler"] / f"crawler_state_{domain_slug}.pkl"),
            "charts_dir": str(output_dirs["charts"]),
        }
        
        return {
            "domain": domain,
            "domain_slug": domain_slug,
            "output_dirs": output_dirs,
            "crawler_config": crawler_config,
            "axe_config": axe_config,
            "report_config": report_config
        }
    
    def domain_to_slug(self, domain: str) -> str:
        """
        Convert a domain to a safe slug for filesystem use.
        
        Args:
            domain: Domain name or URL
            
        Returns:
            Safe slug for filesystem use
        """
        # Remove HTTP/HTTPS and www prefix
        domain = domain.replace("http://", "").replace("https://", "").replace("www.", "")
        
        # Replace non-alphanumeric characters with underscores
        return "".join(c if c.isalnum() else "_" for c in domain)
    
    def get_all_domains(self) -> List[str]:
        """
        Get all configured domains.
        
        Returns:
            List of domains
        """
        return self.get_list("BASE_URLS", [])
    
    def get_pipeline_config(self) -> Dict[str, Any]:
        """
        Get pipeline-specific configuration.
        
        Returns:
            Pipeline configuration
        """
        return {
            "start_stage": self.get("START_STAGE", "crawler"),
            "repeat_axe": self.get_int("REPEAT_ANALYSIS", 1),
            "resource_monitoring": {
                "enabled": self.get_bool("RESOURCE_MONITORING", True),
                "check_interval": self.get_int("RESOURCE_CHECK_INTERVAL", 3),
                "threshold_cpu": self.get_int("CPU_THRESHOLD", 90),
                "threshold_memory": self.get_int("MEMORY_THRESHOLD", 85),
                "cool_down_time": self.get_int("COOL_DOWN_TIME", 7)
            }
        }
    
    def get_logging_config(self) -> Dict[str, Any]:
        """
        Get logging configuration.
        
        Returns:
            Logging configuration
        """
        output_root = self.get_path("OUTPUT_DIR", "~/axeScraper/output")
        log_dir = self.get_path("LOG_DIR", output_root / "logs", create=True)
        
        return {
            "level": self.get("LOG_LEVEL", "INFO"),
            "format": self.get("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            "date_format": self.get("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S"),
            "log_dir": str(log_dir),
            "console_output": self.get_bool("LOG_CONSOLE", True),
            "rotating_logs": self.get_bool("LOG_ROTATING", True),
            "max_bytes": self.get_int("LOG_MAX_BYTES", 10 * 1024 * 1024),  # 10 MB
            "backup_count": self.get_int("LOG_BACKUP_COUNT", 5),
            
            # Component-specific log levels
            "components": {
                "crawler": {
                    "level": self.get("CRAWLER_LOG_LEVEL", self.get("LOG_LEVEL", "INFO")),
                    "log_file": "crawler.log"
                },
                "axe_analysis": {
                    "level": self.get("ANALYSIS_LOG_LEVEL", self.get("LOG_LEVEL", "INFO")),
                    "log_file": "axe_analysis.log"
                },
                "report_analysis": {
                    "level": self.get("REPORT_LOG_LEVEL", self.get("LOG_LEVEL", "INFO")),
                    "log_file": "report_analysis.log"
                },
                "pipeline": {
                    "level": self.get("PIPELINE_LOG_LEVEL", self.get("LOG_LEVEL", "INFO")),
                    "log_file": "pipeline.log"
                }
            }
        }
    
    def get_email_config(self) -> Dict[str, Any]:
        """
        Get email configuration.
        
        Returns:
            Email configuration
        """
        return {
            "recipient_email": self.get("EMAIL_RECIPIENT", "example@example.com"),
            "subject": self.get("EMAIL_SUBJECT", "Accessibility Reports"),
            "body": self.get("EMAIL_BODY", "The accessibility reports are completed. Please find the Excel files attached."),
            "smtp_server": self.get("SMTP_SERVER", "localhost"),
            "smtp_port": self.get_int("SMTP_PORT", 25),
            "smtp_username": self.get("SMTP_USERNAME", ""),
            "smtp_password": self.get("SMTP_PASSWORD", ""),
            "use_tls": self.get_bool("SMTP_TLS", False),
            "mutt_command": self.get("MUTT_COMMAND", "mutt -s"),
        }
    
    def as_dict(self) -> Dict[str, Any]:
        """
        Get all configuration as a dictionary.
        
        Returns:
            Complete configuration dictionary
        """
        config = {}
        
        # General configuration
        config['output_dir'] = str(self.get_path("OUTPUT_DIR", "~/axeScraper/output"))
        config['base_urls'] = self.get_list("BASE_URLS", [])
        
        # Domain configurations
        config['domains'] = {}
        for domain in self.get_all_domains():
            config['domains'][domain] = self.load_domain_config(domain)
        
        # Pipeline configuration
        config['pipeline'] = self.get_pipeline_config()
        
        # Logging configuration
        config['logging'] = self.get_logging_config()
        
        # Email configuration
        config['email'] = self.get_email_config()
        
        return config