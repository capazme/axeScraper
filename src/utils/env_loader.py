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
        env_file_path = None
        
        # Find .env file if not specified
        if not self.env_file:
            # Check common locations
            search_paths = [
                Path.cwd() / '.env',                      # Current directory
                Path.cwd().parent / '.env',               # Parent directory
                Path(__file__).parent.parent.parent / '.env',  # Project root
                Path('/home/ec2-user/axeScraper/.env'),   # Common absolute path
            ]
            
            # Add parent directories up to root
            current_dir = Path.cwd()
            search_paths.extend([p / '.env' for p in current_dir.parents])
            
            # Check all paths
            for path in search_paths:
                if path.exists():
                    env_file_path = path
                    break
        else:
            env_file_path = Path(self.env_file)
            if not env_file_path.exists():
                print(f"Warning: Specified env file {env_file_path} not found")
                env_file_path = None
        
        # If .env file exists, load it
        if env_file_path and env_file_path.exists():
            try:
                print(f"Loading environment from: {env_file_path}")
                with open(env_file_path, 'r') as f:
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
                print(f"Loaded {len(self._env_values)} environment variables from {env_file_path}")
            except Exception as e:
                print(f"Error loading .env file {env_file_path}: {e}")
        else:
            print("No .env file found, using only environment variables")
        
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