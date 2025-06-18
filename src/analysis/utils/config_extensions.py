# src/utils/config_extensions.py
"""
Extensions to the configuration system to support authentication and funnel configurations.
"""

from typing import Dict, Any, Optional
import os
import json
from pathlib import Path

# Additional configuration schema for authentication and funnels
AUTH_FUNNEL_CONFIG_SCHEMA = {
    # Authentication settings
    "AUTH_ENABLED": {
        "type": "bool",
        "default": False,
        "description": "Enable authentication for scanning",
        "aliases": ["authentication.enabled"]
    },
    "AUTH_LOGIN_URL": {
        "type": "str",
        "default": "",
        "description": "URL of the login page",
        "aliases": ["authentication.login_url"]
    },
    "AUTH_USERNAME_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS or XPath selector for the username field",
        "aliases": ["authentication.username_selector"]
    },
    "AUTH_PASSWORD_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS or XPath selector for the password field",
        "aliases": ["authentication.password_selector"]
    },
    "AUTH_SUBMIT_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS or XPath selector for the submit button",
        "aliases": ["authentication.submit_selector"]
    },
    "AUTH_USERNAME": {
        "type": "str",
        "default": "",
        "description": "Username for authentication",
        "aliases": ["authentication.username"]
    },
    "AUTH_PASSWORD": {
        "type": "str",
        "default": "",
        "description": "Password for authentication",
        "aliases": ["authentication.password"]
    },
    "AUTH_SUCCESS_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS or XPath selector to verify successful login",
        "aliases": ["authentication.login_success_selector"]
    },
    "AUTH_SUCCESS_URL": {
        "type": "str",
        "default": "",
        "description": "URL substring to verify successful login",
        "aliases": ["authentication.login_success_url"]
    },
    "AUTH_WAIT_TIME": {
        "type": "int",
        "default": 10,
        "description": "Wait time in seconds for authentication actions",
        "aliases": ["authentication.wait_time"]
    },
    
    # Funnel settings
    "FUNNEL_CONFIG_FILE": {
        "type": "str",
        "default": "",
        "description": "Path to funnel configuration file",
        "aliases": ["funnel_config_file"]
    },
    "FUNNEL_ENABLED": {
        "type": "bool",
        "default": False,
        "description": "Enable funnel-based scanning",
        "aliases": ["funnel.enabled"]
    }
}

def get_auth_config(config_manager) -> Dict[str, Any]:
    """
    Get authentication configuration from the config manager.
    
    Args:
        config_manager: ConfigurationManager instance
        
    Returns:
        Dict: Authentication configuration
    """
    # Check if we should load from separate config file
    auth_config_file = config_manager.get("AUTH_CONFIG_FILE", "")
    
    if auth_config_file and os.path.exists(auth_config_file):
        # Load from file
        try:
            with open(auth_config_file, 'r') as f:
                auth_config = json.load(f)
                
            # If the config has an 'authentication' key, use that
            if 'authentication' in auth_config:
                return auth_config['authentication']
            return auth_config
        except Exception as e:
            config_manager.logger.error(f"Error loading authentication config from {auth_config_file}: {e}")
            return {"enabled": False}
    
    # Build from individual settings
    auth_config = {
        "enabled": config_manager.get_bool("AUTH_ENABLED", False),
        "login_url": config_manager.get("AUTH_LOGIN_URL", ""),
        "username_selector": config_manager.get("AUTH_USERNAME_SELECTOR", ""),
        "password_selector": config_manager.get("AUTH_PASSWORD_SELECTOR", ""),
        "submit_selector": config_manager.get("AUTH_SUBMIT_SELECTOR", ""),
        "username": config_manager.get("AUTH_USERNAME", ""),
        "password": config_manager.get("AUTH_PASSWORD", ""),
        "login_success_selector": config_manager.get("AUTH_SUCCESS_SELECTOR", ""),
        "login_success_url": config_manager.get("AUTH_SUCCESS_URL", ""),
        "wait_time": config_manager.get_int("AUTH_WAIT_TIME", 10)
    }
    
    return auth_config

def get_funnel_config(config_manager) -> Dict[str, Any]:
    """
    Get funnel configuration from the config manager.
    
    Args:
        config_manager: ConfigurationManager instance
        
    Returns:
        Dict: Funnel configuration
    """
    # Check if we should load from separate config file
    funnel_config_file = config_manager.get("FUNNEL_CONFIG_FILE", "")
    
    if funnel_config_file and os.path.exists(funnel_config_file):
        # Load from file
        try:
            with open(funnel_config_file, 'r') as f:
                funnel_config = json.load(f)
                
            # If the config has a 'funnels' key, use that structure
            if 'funnels' not in funnel_config:
                funnel_config = {'funnels': funnel_config}
                
            # Add enabled flag
            funnel_config['enabled'] = config_manager.get_bool("FUNNEL_ENABLED", True)
            return funnel_config
        except Exception as e:
            config_manager.logger.error(f"Error loading funnel config from {funnel_config_file}: {e}")
            return {"enabled": False, "funnels": []}
    
    # If no file is specified or it doesn't exist, return empty config
    return {
        "enabled": config_manager.get_bool("FUNNEL_ENABLED", False),
        "funnels": []
    }


def load_external_config(file_path: str) -> Dict[str, Any]:
    """
    Load configuration from an external JSON file.
    
    Args:
        file_path: Path to the JSON configuration file
        
    Returns:
        Dict: Configuration dictionary
    """
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading configuration from {file_path}: {e}")
        return {}