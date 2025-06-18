"""
Enhanced configuration module for axeScraper.
Centralizes configuration settings and provides environment-based overrides.
"""

import os
import json
import multiprocessing
from pathlib import Path
from typing import Dict, Any, List, Union, Optional
from urllib.parse import urlparse

# ========== Helper Functions ==========

def get_env(var_name: str, default: Any = None) -> Any:
    """
    Get an environment variable or return a default value.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if the variable is not set
        
    Returns:
        Value of the environment variable or default
    """
    return os.environ.get(var_name, default)

def get_env_bool(var_name: str, default: bool = False) -> bool:
    """
    Get a boolean environment variable or return a default value.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if the variable is not set
        
    Returns:
        Boolean value of the environment variable or default
    """
    value = get_env(var_name, "").lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    return default

def get_env_int(var_name: str, default: int = 0) -> int:
    """
    Get an integer environment variable or return a default value.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if the variable is not set
        
    Returns:
        Integer value of the environment variable or default
    """
    try:
        return int(get_env(var_name, default))
    except (ValueError, TypeError):
        return default

def get_env_float(var_name: str, default: float = 0.0) -> float:
    """
    Get a float environment variable or return a default value.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if the variable is not set
        
    Returns:
        Float value of the environment variable or default
    """
    try:
        return float(get_env(var_name, default))
    except (ValueError, TypeError):
        return default

def get_env_list(var_name: str, default: List[str] = None, separator: str = ",") -> List[str]:
    """
    Get a list environment variable or return a default value.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if the variable is not set
        separator: Separator to split the string into a list
        
    Returns:
        List value of the environment variable or default
    """
    if default is None:
        default = []
    value = get_env(var_name)
    if not value:
        return default
    return [item.strip() for item in value.split(separator)]

def generate_safe_slug(url: str) -> str:
    """
    Generate a safe slug from a URL or domain name.
    
    Args:
        url: URL or domain name
        
    Returns:
        Safe slug for filesystem use
    """
    try:
        if url.startswith(("http://", "https://")):
            parsed = urlparse(url)
            domain = parsed.netloc
        else:
            domain = url
            
        # Remove www. prefix
        domain = domain.replace("www.", "")
        
        # Replace non-alphanumeric characters with underscores
        return "".join(c if c.isalnum() else "_" for c in domain).lower()
    except Exception:
        # Fallback for invalid URLs
        return "unknown_domain"

# ========== Environment-aware configurations ==========

# Get configuration file path from environment or use default
CONFIG_FILE = get_env("AXE_CONFIG_FILE", "")

# Get base directory for output from environment or use default
OUTPUT_ROOT = get_env("AXE_OUTPUT_DIR", os.path.expanduser("~/axeScraper/output"))

# Resource calculation based on system
CPU_COUNT = multiprocessing.cpu_count()
DEFAULT_MAX_WORKERS = min(CPU_COUNT * 2, 32)  # 2 workers per CPU, max 32
SELENIUM_POOL_SIZE = max(2, CPU_COUNT // 2)  # Pool of driver for Selenium

# Load configuration from file if specified
if CONFIG_FILE and os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            if CONFIG_FILE.endswith('.json'):
                config_data = json.load(f)
            elif CONFIG_FILE.endswith(('.yml', '.yaml')):
                import yaml
                config_data = yaml.safe_load(f)
            else:
                # Assume Python module with dict variables
                import importlib.util
                spec = importlib.util.spec_from_file_location("config_module", CONFIG_FILE)
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)
                config_data = {name: value for name, value in vars(config_module).items() 
                            if not name.startswith('_') and isinstance(value, (dict, list, str, int, float, bool))}
        
        # Extract configurations
        if "OUTPUT_ROOT" in config_data:
            OUTPUT_ROOT = config_data["OUTPUT_ROOT"]
        if "BASE_URLS" in config_data:
            BASE_URLS = config_data["BASE_URLS"]
        # Additional configuration extraction can be added here
        
    except Exception as e:
        print(f"Error loading configuration file {CONFIG_FILE}: {e}")
        # Continue with default configuration

# ========== Base Configuration ==========

# Get base URLs from environment or use defaults
BASE_URLS = get_env_list("AXE_BASE_URLS", ["iccreabanca.it/it-IT/Pagine/default.aspx"])

# Create domain output structure
def create_domain_output_structure(base_urls: List[str], root_output_dir: str) -> Dict[str, Dict[str, Path]]:
    """
    Create a structure of directories dedicated to each domain.
    
    Args:
        base_urls: List of URLs to analyze
        root_output_dir: Root directory for all outputs
    
    Returns:
        Dictionary with output structures for each domain
    """
    domain_outputs = {}
    
    for base_url in base_urls:
        # Generate a safe slug for the domain
        DOMAIN_SLUG = generate_safe_slug(base_url)
        
        # Create root directory for the domain
        domain_root = Path(root_output_dir) / DOMAIN_SLUG
        
        # Directory structure for each domain
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
        
        domain_outputs[base_url] = output_dirs
    
    return domain_outputs

# Generate the structures of output for the domains
DOMAIN_OUTPUTS = create_domain_output_structure(BASE_URLS, OUTPUT_ROOT)

# ========== URL Configuration ==========

def get_url_config(base_url: str) -> Dict[str, Any]:
    """
    Generate configuration for a specific URL.
    
    Args:
        base_url: Base URL to generate configuration for
    
    Returns:
        Configuration dictionary for the URL
    """
    # Get output directories for this domain
    domain_dirs = DOMAIN_OUTPUTS[base_url]
    
    # Generate a safe slug for the domain
    DOMAIN_SLUG = generate_safe_slug(base_url)
    
    # Extract domain for multi_domain_crawler
    domains = base_url
    parsed_url = urlparse(base_url)
    domain_name = parsed_url.netloc.replace("www.", "")
    
    return {
        "crawler_config": {
            "base_url": base_url,
            "domains": domain_name,  # Just the domain, not the full URL for multi_domain_crawler
            "max_workers": get_env_int("AXE_CRAWLER_MAX_WORKERS", DEFAULT_MAX_WORKERS),
            "state_file": str(domain_dirs["crawler"] / f"crawler_state_{DOMAIN_SLUG}.pkl"),
            "max_urls": get_env_int("AXE_CRAWLER_MAX_URLS", 100),
            "max_retries": get_env_int("AXE_CRAWLER_MAX_RETRIES", 10),
            "request_delay": get_env_float("AXE_CRAWLER_REQUEST_DELAY", 0.25),
            "selenium_browser": get_env_bool("AXE_CRAWLER_USE_SELENIUM", False),
            "output_markdown": str(domain_dirs["reports"] / f"site_structure_{DOMAIN_SLUG}.md"),
            "hybrid_mode": get_env_bool("AXE_CRAWLER_HYBRID_MODE", True),
            "pending_threshold": get_env_int("AXE_CRAWLER_PENDING_THRESHOLD", 250),
            
            # Specific parameters for multi_domain_crawler
            "selenium_pool_size": SELENIUM_POOL_SIZE,
            "parser_workers": get_env_int("AXE_CRAWLER_PARSER_WORKERS", CPU_COUNT // 2),
            "template_cache_size": get_env_int("AXE_CRAWLER_TEMPLATE_CACHE", 10000),
            "html_cache_size": get_env_int("AXE_CRAWLER_HTML_CACHE", 10000),
            "auto_save_interval": get_env_int("AXE_CRAWLER_SAVE_INTERVAL", 20),
            "aiohttp_connections_limit": get_env_int("AXE_CRAWLER_CONNECTIONS", 100),
            "aiohttp_timeout": get_env_int("AXE_CRAWLER_TIMEOUT", 60),
            
            # Crawler output path
            "output_dir": str(domain_dirs["crawler"]),
        },
        "axe_analysis_config": {
            "analysis_state_file": str(domain_dirs["crawler"] / f"crawler_state_{DOMAIN_SLUG}.pkl"),
            "domains": domain_name,  # Added for multi_domain_crawler
            "max_templates_per_domain": get_env_int("AXE_MAX_TEMPLATES", None),
            "fallback_urls": [base_url],
            "pool_size": get_env_int("AXE_POOL_SIZE", 5),
            "sleep_time": get_env_float("AXE_SLEEP_TIME", 1),
            "excel_filename": str(domain_dirs["axe"] / f"accessibility_report_{DOMAIN_SLUG}.xlsx"),
            "visited_file": str(domain_dirs["axe"] / f"visited_urls_{DOMAIN_SLUG}.txt"),
            "headless": get_env_bool("AXE_HEADLESS", True),
            "resume": get_env_bool("AXE_RESUME", True),
            "output_folder": str(domain_dirs["axe"]),
        },
        "final_report_config": {
            "input_excel": str(domain_dirs["axe"] / f"accessibility_report_{DOMAIN_SLUG}.xlsx"),
            "output_concat": str(domain_dirs["analysis"] / f"{DOMAIN_SLUG}_concat.xlsx"),
            "output_excel": str(domain_dirs["analysis"] / f"final_analysis_{DOMAIN_SLUG}.xlsx"),
            "crawler_state_file": str(domain_dirs["crawler"] / f"crawler_state_{DOMAIN_SLUG}.pkl"),
            "charts_output_dir": str(domain_dirs["charts"]),
        },
        "output_dirs": domain_dirs
    }

# Generate configuration for all URLs
URL_CONFIGS = {url: get_url_config(url) for url in BASE_URLS}

# ========== Global Configuration ==========

# Pipeline configuration
PIPELINE_CONFIG = {
    # Start stage can be "crawler", "axe", or "final"
    "start_stage": get_env("AXE_START_STAGE", "crawler"),
    
    # Number of times to repeat the Axe analysis
    "repeat_axe": get_env_int("AXE_REPEAT_ANALYSIS", 1),
    
    # Resource monitoring
    "resource_monitoring": {
        "enabled": get_env_bool("AXE_RESOURCE_MONITORING", True),
        "check_interval": get_env_int("AXE_RESOURCE_CHECK_INTERVAL", 3),
        "threshold_cpu": get_env_int("AXE_CPU_THRESHOLD", 90),
        "threshold_memory": get_env_int("AXE_MEMORY_THRESHOLD", 85),
        "cool_down_time": get_env_int("AXE_COOL_DOWN_TIME", 7)
    },
    
    # Multi-domain crawler
    "multi_domain_crawler": {
        "use_subprocess": get_env_bool("AXE_CRAWLER_SUBPROCESS", True),
        "scrapy_settings": {
            "CONCURRENT_REQUESTS": get_env_int("AXE_SCRAPY_CONCURRENT_REQUESTS", 16),
            "CONCURRENT_REQUESTS_PER_DOMAIN": get_env_int("AXE_SCRAPY_CONCURRENT_PER_DOMAIN", 8),
            "DOWNLOAD_DELAY": get_env_float("AXE_SCRAPY_DOWNLOAD_DELAY", 0.25),
            "AUTOTHROTTLE_ENABLED": get_env_bool("AXE_SCRAPY_AUTOTHROTTLE", True),
            "DOWNLOAD_TIMEOUT": get_env_int("AXE_SCRAPY_TIMEOUT", 30),
            "RETRY_TIMES": get_env_int("AXE_SCRAPY_RETRY_TIMES", 3)
        }
    }
}

# Email configuration
EMAIL_CONFIG = {
    "recipient_email": get_env("AXE_EMAIL_RECIPIENT", "roma.01@sapglegal.com"),
    "subject": get_env("AXE_EMAIL_SUBJECT", "Accessibility Reports"),
    "body": get_env("AXE_EMAIL_BODY", "The accessibility reports are completed. Please find the Excel files attached."),
    "smtp_server": get_env("AXE_SMTP_SERVER", "localhost"),
    "smtp_port": get_env_int("AXE_SMTP_PORT", 25),
    "smtp_username": get_env("AXE_SMTP_USERNAME", ""),
    "smtp_password": get_env("AXE_SMTP_PASSWORD", ""),
    "use_tls": get_env_bool("AXE_SMTP_TLS", False),
    "mutt_command": get_env("AXE_MUTT_COMMAND", "mutt -s"),
}

# Logging configuration
LOGGING_CONFIG = {
    "level": get_env("AXE_LOG_LEVEL", "INFO"),
    "format": get_env("AXE_LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
    "date_format": get_env("AXE_LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S"),
    "log_dir": get_env("AXE_LOG_DIR", os.path.join(OUTPUT_ROOT, "logs")),
    "console_output": get_env_bool("AXE_LOG_CONSOLE", True),
    "rotating_logs": get_env_bool("AXE_LOG_ROTATING", True),
    "max_bytes": get_env_int("AXE_LOG_MAX_BYTES", 10 * 1024 * 1024),  # 10 MB
    "backup_count": get_env_int("AXE_LOG_BACKUP_COUNT", 5),
    
    # Component-specific override
    "components": {
        "crawler": {
            "level": get_env("AXE_CRAWLER_LOG_LEVEL", "INFO"),
            "log_file": "crawler.log"
        },
        "axe_analysis": {
            "level": get_env("AXE_ANALYSIS_LOG_LEVEL", "INFO"),
            "log_file": "axe_analysis.log"
        },
        "report_analysis": {
            "level": get_env("AXE_REPORT_LOG_LEVEL", "INFO"),
            "log_file": "report_analysis.log"
        },
        "pipeline": {
            "level": get_env("AXE_PIPELINE_LOG_LEVEL", "INFO"),
            "log_file": "pipeline.log"
        }
    }
}

# Output directory configuration
OUTPUT_CONFIG = {
    "base_dir": OUTPUT_ROOT,
    "create_dirs_on_startup": get_env_bool("AXE_CREATE_DIRS", True),
    "use_timestamp": get_env_bool("AXE_USE_TIMESTAMP", True),
    "timestamp_format": get_env("AXE_TIMESTAMP_FORMAT", "%Y%m%d_%H%M%S"),
    "backup_old_outputs": get_env_bool("AXE_BACKUP_OUTPUTS", True),
    "max_backups": get_env_int("AXE_MAX_BACKUPS", 5),
    
    # Component-specific overrides
    "components": {
        "crawler": {
            "subdirectory": "crawler_output",
            "file_patterns": {
                "state": "crawler_state_{DOMAIN_SLUG}.pkl",
                "log": "crawler_{timestamp}.log",
                "report": "crawler_report_{DOMAIN_SLUG}_{timestamp}.{ext}"
            }
        },
        "axe": {
            "subdirectory": "axe_output",
            "file_patterns": {
                "excel": "accessibility_report_{DOMAIN_SLUG}.xlsx",
                "visited": "visited_urls_{DOMAIN_SLUG}.txt"
            }
        },
        "analysis": {
            "subdirectory": "analysis_output",
            "file_patterns": {
                "excel": "final_analysis_{DOMAIN_SLUG}.xlsx",
                "concat": "{DOMAIN_SLUG}_concat.xlsx"
            }
        }
    }
}

# Version information
VERSION = "1.0.0"