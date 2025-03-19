# src/utils/env_loader.py
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, TypeVar, cast

T = TypeVar('T')

class EnvLoader:
    """
    Enhanced loader for environment variables with proper type conversion
    and hierarchical loading from multiple sources.
    """
    
    def __init__(self, env_file: Optional[Union[str, Path]] = None):
        """
        Initialize the environment loader.
        
        Args:
            env_file: Path to .env file (or None to auto-detect)
        """
        self.env_file = env_file
        self._loaded = False
        self._env_values = {}
        
    def load(self, auto_reload: bool = False) -> Dict[str, str]:
        """
        Load environment variables from .env file.
        
        Args:
            auto_reload: Whether to reload even if already loaded
            
        Returns:
            Dictionary of loaded environment variables
        """
        if self._loaded and not auto_reload:
            return self._env_values
            
        self._env_values = {}
        
        # Find .env file if not specified
        if not self.env_file:
            # Search in current directory and parent directories
            current_dir = Path.cwd()
            potential_paths = [current_dir]
            potential_paths.extend(current_dir.parents)
            
            for path in potential_paths:
                env_path = path / '.env'
                if env_path.exists():
                    self.env_file = env_path
                    break
        
        # If .env file exists, load it
        if self.env_file and Path(self.env_file).exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                        
                    # Handle variable assignments
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes if present
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                            
                        # Handle variable substitution
                        if '$' in value:
                            value = self._substitute_variables(value)
                            
                        # Store the value
                        self._env_values[key] = value
                        
                        # Also set as environment variable if not already set
                        if key not in os.environ:
                            os.environ[key] = value
        
        self._loaded = True
        return self._env_values
    
    def _substitute_variables(self, value: str) -> str:
        """
        Substitute environment variables in a string.
        
        Args:
            value: String with potential variable references
            
        Returns:
            String with variables replaced by their values
        """
        # Match ${VAR} or $VAR patterns
        pattern = r'\${([^}]+)}|\$([a-zA-Z0-9_]+)'
        
        def replace_var(match):
            var_name = match.group(1) or match.group(2)
            # Check in already loaded values, then in environment
            return self._env_values.get(var_name, os.environ.get(var_name, ''))
            
        return re.sub(pattern, replace_var, value)
    
    def get(self, key: str, default: Optional[T] = None) -> Union[str, T]:
        """
        Get an environment variable with optional default.
        
        Args:
            key: Environment variable name
            default: Default value if not found
            
        Returns:
            Environment variable value or default
        """
        if not self._loaded:
            self.load()
            
        # Check in environment first, then in loaded values
        return os.environ.get(key, self._env_values.get(key, default))
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        Get a boolean environment variable.
        
        Args:
            key: Environment variable name
            default: Default value if not found
            
        Returns:
            Boolean value of environment variable
        """
        value = self.get(key, "")
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
        Get an integer environment variable.
        
        Args:
            key: Environment variable name
            default: Default value if not found
            
        Returns:
            Integer value of environment variable
        """
        value = self.get(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    def get_float(self, key: str, default: float = 0.0) -> float:
        """
        Get a float environment variable.
        
        Args:
            key: Environment variable name
            default: Default value if not found
            
        Returns:
            Float value of environment variable
        """
        value = self.get(key, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def get_list(self, key: str, default: Optional[List[str]] = None, 
                 separator: str = ',') -> List[str]:
        """
        Get a list environment variable.
        
        Args:
            key: Environment variable name
            default: Default value if not found
            separator: Separator to split the string into a list
            
        Returns:
            List value of environment variable
        """
        if default is None:
            default = []
            
        value = self.get(key, "")
        if not value:
            return default
            
        if isinstance(value, list):
            return value
            
        if isinstance(value, str):
            return [item.strip() for item in value.split(separator)]
            
        return default
    
    def get_path(self, key: str, default: Optional[Union[str, Path]] = None,
                expand_user: bool = True) -> Path:
        """
        Get a path environment variable.
        
        Args:
            key: Environment variable name
            default: Default value if not found
            expand_user: Whether to expand user directory (~/...)
            
        Returns:
            Path object for environment variable
        """
        value = self.get(key, default)
        if value is None:
            # Create a default temporary directory
            import tempfile
            return Path(tempfile.gettempdir())
            
        path = Path(value)
        if expand_user:
            path = path.expanduser()
            
        return path