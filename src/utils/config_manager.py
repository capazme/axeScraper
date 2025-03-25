# src/utils/config_manager.py
import os
import json
import yaml
import logging
import multiprocessing
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, TypeVar, Set, Callable
import datetime
from utils.config_schema_additions import CONFIG_SCHEMA_ADDITIONS

T = TypeVar('T')
_CONFIG_MANAGER_INSTANCE = None
_INITIALIZING = False  # Flag to prevent recursion

def get_config_manager(project_name="axeScraper", config_file=None, cli_args=None):
    global _CONFIG_MANAGER_INSTANCE, _INITIALIZING
    if _CONFIG_MANAGER_INSTANCE is None and not _INITIALIZING:
        _INITIALIZING = True  # Set flag before initializing
        _CONFIG_MANAGER_INSTANCE = ConfigurationManager(project_name, config_file, cli_args=cli_args)
        _INITIALIZING = False  # Reset flag after initialization
    return _CONFIG_MANAGER_INSTANCE


# Definizione dello schema di configurazione
DEFAULT_CONFIG_SCHEMA = {
    # Configurazione Crawler
    "CRAWLER_MAX_URLS": {
        "type": "int",
        "default": 100,
        "description": "Numero massimo di URL per dominio",
        "aliases": ["max_urls_per_domain", "max_urls"]
    },
    "CRAWLER_HYBRID_MODE": {
        "type": "bool",
        "default": True,
        "description": "Modalità ibrida (Selenium + HTTP)",
        "aliases": ["hybrid_mode"]
    },
    "CRAWLER_REQUEST_DELAY": {
        "type": "float",
        "default": 0.25,
        "description": "Ritardo tra le richieste in secondi",
        "aliases": ["request_delay"]
    },
    "CRAWLER_PENDING_THRESHOLD": {
        "type": "int",
        "default": 30, 
        "description": "Soglia per passare da Selenium a HTTP",
        "aliases": ["selenium_threshold", "pending_threshold"]
    },
    "CRAWLER_MAX_WORKERS": {
        "type": "int",
        "default": 16,
        "description": "Numero massimo di worker concorrenti",
        "aliases": ["max_workers"]
    },
    
    # Configurazione Axe
    "AXE_MAX_TEMPLATES": {
        "type": "int",
        "default": 50,
        "description": "Massimo numero di template da analizzare",
        "aliases": ["max_templates_per_domain"]
    },
    "AXE_POOL_SIZE": {
        "type": "int",
        "default": 5,
        "description": "Dimensione del pool di driver Selenium",
        "aliases": ["pool_size"]
    },
    "AXE_SLEEP_TIME": {
        "type": "float",
        "default": 1.0,
        "description": "Tempo di attesa tra le richieste Axe",
        "aliases": ["sleep_time"]
    },
    "AXE_HEADLESS": {
        "type": "bool",
        "default": True,
        "description": "Modalità headless per Selenium",
        "aliases": ["headless"]
    },
    "AXE_RESUME": {
        "type": "bool",
        "default": True,
        "description": "Riprendi l'analisi da dove interrotta",
        "aliases": ["resume"]
    },
    
    # Configurazione Pipeline
    "START_STAGE": {
        "type": "str",
        "default": "crawler",
        "description": "Stadio iniziale della pipeline",
        "allowed_values": ["crawler", "axe", "analysis"]
    },
    "REPEAT_ANALYSIS": {
        "type": "int",
        "default": 1,
        "description": "Numero di volte da ripetere l'analisi Axe",
        "aliases": ["repeat_axe"]
    },
    
    # Configurazione Generale
    "BASE_URLS": {
        "type": "list",
        "default": [],
        "description": "URL di base da analizzare"
    },
    "OUTPUT_DIR": {
        "type": "path",
        "default": "~/axeScraper/output",
        "description": "Directory di base per l'output"
    }
}

class ConfigurationManager:
    """
    Gestore centralizzato delle configurazioni che integra più fonti:
    - Argomenti da linea di comando (priorità massima)
    - Variabili d'ambiente
    - File di configurazione (.json, .yaml, ecc.)
    - Valori predefiniti (priorità minima)
    """
    
    def __init__(
        self,
        project_name: str = "axeScraper",
        config_file: Optional[Union[str, Path]] = None,
        config_schema: Optional[Dict[str, Dict[str, Any]]] = None,
        cli_args: Optional[Dict[str, Any]] = None
    ):
        """
        Inizializza il gestore di configurazione.
        
        Args:
            project_name: Nome del progetto
            config_file: Percorso del file di configurazione
            config_schema: Schema di configurazione personalizzato
            cli_args: Argomenti da linea di comando
        """
        self.project_name = project_name
        self.config_file = self._find_config_file(config_file)
        self.cli_args = cli_args or {}
        
        # Initialize schema with default schema and additions
        base_schema = DEFAULT_CONFIG_SCHEMA.copy()
        
        # Add authentication and funnel schema
        base_schema.update(CONFIG_SCHEMA_ADDITIONS)
        
        # Use custom schema if provided, otherwise use the enhanced base schema
        self.config_schema = config_schema or base_schema
        
        # Alias mapping
        self.aliases = self._build_alias_mapping()
        
        # Set up a simple logger directly without using get_logger() function
        self.logger = logging.getLogger(f"{project_name}.config")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            self.logger.propagate = False  # Prevent propagation

        
        # Informazioni sul sistema
        self.cpu_count = multiprocessing.cpu_count()
        self.init_time = datetime.datetime.now()
        
        # Configurazione caricata da file
        self._file_config = {}
        
        # Cache delle configurazioni
        self._config_cache = {}
        
        # Flag di debug
        self.debug_mode = False
        
        # Carica le configurazioni
        self.reload_config()
        
        self.logger.info(f"ConfigurationManager inizializzato: {project_name}")
        self.logger.info(f"File configurazione: {self.config_file}")
    
    def _build_alias_mapping(self) -> Dict[str, str]:
        """Costruisce un mapping da alias a chiavi standard"""
        aliases = {}
        for key, config in self.config_schema.items():
            for alias in config.get("aliases", []):
                aliases[alias] = key
        return aliases
    
    def _find_config_file(self, config_file: Optional[Union[str, Path]]) -> Optional[Path]:
        if config_file:
            return Path(config_file)
        search_paths = [
            Path.cwd() / 'config.json',
            Path.cwd() / 'config.yaml',
            Path.cwd() / 'config.yml',
            Path.cwd().parent / 'config.json',
            Path.home() / 'axeScraper' / 'config.json',
            Path('/etc/axeScraper/config.json')
        ]
        for path in search_paths:
            if path.exists():
                return path
        return None

    def reload_config(self) -> bool:
        """Ricarica tutte le configurazioni."""
        # Svuota la cache
        self._config_cache = {}
        # Carica la configurazione da file
        self._load_file_config()
        self.logger.info("Configurazione ricaricata")
        
        # Log dei valori chiave
        self._log_key_config_values()
        
        return True
    
    def _log_key_config_values(self) -> None:
        """Logga i valori delle configurazioni chiave."""
        self.logger.info("=== Valori di configurazione chiave ===")
        
        # Crawler
        max_urls = self.get_int("CRAWLER_MAX_URLS")
        hybrid_mode = self.get_bool("CRAWLER_HYBRID_MODE")
        threshold = self.get_int("CRAWLER_PENDING_THRESHOLD")
        
        self.logger.info(f"CRAWLER_MAX_URLS = {max_urls}")
        self.logger.info(f"CRAWLER_HYBRID_MODE = {hybrid_mode}")
        self.logger.info(f"CRAWLER_PENDING_THRESHOLD = {threshold}")
        
        # Axe
        templates = self.get_int("AXE_MAX_TEMPLATES")
        pool_size = self.get_int("AXE_POOL_SIZE")
        
        self.logger.info(f"AXE_MAX_TEMPLATES = {templates}")
        self.logger.info(f"AXE_POOL_SIZE = {pool_size}")
        
        # Pipeline
        stage = self.get("START_STAGE")
        repeat = self.get_int("REPEAT_ANALYSIS")
        
        self.logger.info(f"START_STAGE = {stage}")
        self.logger.info(f"REPEAT_ANALYSIS = {repeat}")
        
        self.logger.info("================================")
    
    def _load_file_config(self) -> Dict[str, Any]:
        """Carica la configurazione da file."""
        self._file_config = {}
        if not self.config_file or not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, 'r') as f:
                if self.config_file.suffix.lower() == '.json':
                    self._file_config = json.load(f)
                elif self.config_file.suffix.lower() in ('.yaml', '.yml'):
                    self._file_config = yaml.safe_load(f)
                else:
                    # Tenta di parsare come file key=value
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            key, value = line.split('=', 1)
                            self._file_config[key.strip()] = value.strip()
            if self.debug_mode:
                self.logger.debug(f"Loaded configuration from file: {self.config_file}")
            return self._file_config
        except Exception as e:
            self.logger.error(f"Errore caricando il file di configurazione {self.config_file}: {e}")
            return {}
    
    def _normalize_key(self, key: str) -> str:
        """Normalizza una chiave di configurazione usando gli alias."""
        # Se la chiave è già standardizzata, restituiscila com'è
        if key in self.config_schema:
            return key
        
        # Controlla se è un alias noto
        if key in self.aliases:
            standardized = self.aliases[key]
            if self.debug_mode:
                self.logger.debug(f"Normalizzato alias '{key}' a '{standardized}'")
            return standardized
        
        # Altrimenti restituisci la chiave originale
        return key
    
    def get(
        self, 
        key: str, 
        default: Optional[T] = None,
        transform: Optional[Callable[[Any], T]] = None,
        use_cache: bool = True
    ) -> T:
        """
        Ottiene un valore di configurazione con gestione delle priorità.
        
        Ordine di priorità:
        1. Argomenti da linea di comando
        2. File di configurazione
        3. Valore predefinito dallo schema
        4. Valore predefinito fornito
        """
        # Normalizza la chiave
        std_key = self._normalize_key(key)
        
        # Gestisci la cache
        cache_key = f"{std_key}_{key}"  # Usa entrambi per distinguere richieste esplicite
        if not use_cache and cache_key in self._config_cache:
            del self._config_cache[cache_key]
        if use_cache and cache_key in self._config_cache:
            return self._config_cache[cache_key]
        
        # Inizializza con il valore predefinito più appropriato
        schema_default = None
        if std_key in self.config_schema:
            schema_default = self.config_schema[std_key].get('default')
            
        # Valore finale predefinito (schema o fornito)
        final_default = default if default is not None else schema_default
        
        # 1. Argomenti da linea di comando (controlla sia la chiave standard che gli alias)
        if std_key in self.cli_args:
            value = self.cli_args[std_key]
            source = "CLI args (std key)"
        elif key in self.cli_args:
            value = self.cli_args[key]
            source = "CLI args (alias)"
        else:
            # 2. File di configurazione (controlla sia la chiave standard che gli alias)
            file_value = None
            
            # Controllo nidificato (e.g., "crawler.max_urls")
            if '.' in std_key:
                parts = std_key.split('.')
                config = self._file_config
                for part in parts:
                    if not isinstance(config, dict) or part not in config:
                        config = None
                        break
                    config = config[part]
                file_value = config
            else:
                # Controllo diretto sulla chiave standard
                if std_key in self._file_config:
                    file_value = self._file_config[std_key]
                # Controllo sulla chiave originale (potrebbe essere un alias)
                elif key in self._file_config:
                    file_value = self._file_config[key]
            
            if file_value is not None:
                value = file_value
                source = "config file"
            else:
                # 3. Valore predefinito
                value = final_default
                source = "default value"
        
        # Applica eventuale trasformazione
        if transform and value is not None:
            try:
                value = transform(value)
            except Exception as e:
                self.logger.warning(f"Errore trasformando valore per {key}: {e}")
                value = final_default
        
        # Applica validazione dallo schema
        if std_key in self.config_schema:
            schema = self.config_schema[std_key]
            
            # Validazione del tipo
            expected_type = schema.get('type')
            if expected_type == 'int' and not isinstance(value, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    self.logger.warning(f"Tipo non valido per {std_key} (atteso int): {value}")
                    value = schema.get('default')
            elif expected_type == 'bool' and not isinstance(value, bool):
                if isinstance(value, str):
                    value = value.lower() in ('1', 'true', 'yes', 'y', 'on')
                else:
                    value = bool(value)
            elif expected_type == 'float' and not isinstance(value, float):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    self.logger.warning(f"Tipo non valido per {std_key} (atteso float): {value}")
                    value = schema.get('default')
            
            # Validazione del valore
            allowed_values = schema.get('allowed_values')
            if allowed_values and value not in allowed_values:
                self.logger.warning(f"Valore non valido per {std_key}: {value}. Valori consentiti: {allowed_values}")
                value = schema.get('default')
        
        if self.debug_mode:
            self.logger.debug(f"Config get: {key} ({std_key}) = {value} (from {source})")
        
        self._config_cache[cache_key] = value
        return value

    def get_bool(self, key: str, default: bool = None) -> bool:
        """
        Ottiene un valore booleano.
        
        Args:
            key: Chiave di configurazione
            default: Valore predefinito se non trovato
            
        Returns:
            Valore booleano
        """
        schema_default = None
        std_key = self._normalize_key(key)
        
        if std_key in self.config_schema and self.config_schema[std_key]['type'] == 'bool':
            schema_default = self.config_schema[std_key].get('default')
            
        final_default = default if default is not None else schema_default
        
        return self.get(key, final_default, lambda v: self._to_bool(v, final_default))
    
    def _to_bool(self, value: Any, default: bool) -> bool:
        """Converte un valore in booleano."""
        if isinstance(value, bool):
            return value
            
        if isinstance(value, str):
            value = value.lower()
            if value in ('1', 'true', 'yes', 'y', 'on'):
                return True
            if value in ('0', 'false', 'no', 'n', 'off'):
                return False
                
        return bool(value) if value is not None else default
    
    def get_int(self, key: str, default: int = None) -> int:
        """
        Ottiene un valore intero.
        
        Args:
            key: Chiave di configurazione
            default: Valore predefinito se non trovato
            
        Returns:
            Valore intero
        """
        schema_default = None
        std_key = self._normalize_key(key)
        
        if std_key in self.config_schema and self.config_schema[std_key]['type'] == 'int':
            schema_default = self.config_schema[std_key].get('default')
            
        final_default = default if default is not None else schema_default
        
        try:
            return int(self.get(key, final_default))
        except (ValueError, TypeError):
            return final_default
    
    def get_float(self, key: str, default: float = None) -> float:
        """
        Ottiene un valore float.
        
        Args:
            key: Chiave di configurazione
            default: Valore predefinito se non trovato
            
        Returns:
            Valore float
        """
        schema_default = None
        std_key = self._normalize_key(key)
        
        if std_key in self.config_schema and self.config_schema[std_key]['type'] == 'float':
            schema_default = self.config_schema[std_key].get('default')
            
        final_default = default if default is not None else schema_default
        
        try:
            return float(self.get(key, final_default))
        except (ValueError, TypeError):
            return final_default
    
    def get_list(
        self, 
        key: str, 
        default: Optional[List[str]] = None,
        separator: str = ','
    ) -> List[str]:
        """
        Ottiene un valore lista.
        
        Args:
            key: Chiave di configurazione
            default: Valore predefinito se non trovato
            separator: Separatore per dividere la stringa in lista
            
        Returns:
            Valore lista
        """
        schema_default = None
        std_key = self._normalize_key(key)
        
        if std_key in self.config_schema and self.config_schema[std_key]['type'] == 'list':
            schema_default = self.config_schema[std_key].get('default')
            
        final_default = default if default is not None else schema_default
        if final_default is None:
            final_default = []
            
        return self.get(key, final_default, lambda v: self._to_list(v, separator, final_default))
    
    def _to_list(self, value: Any, separator: str, default: List[str]) -> List[str]:
        """Converte un valore in lista."""
        if isinstance(value, list):
            return value
            
        if isinstance(value, str):
            # Gestisce il caso in cui la stringa rappresenti una lista vuota
            if value in ('[]', '""', "''", ''):
                return []
            return [item.strip() for item in value.split(separator) if item.strip()]
            
        return default
    
    def get_path(
        self, 
        key: str, 
        default: Optional[Union[str, Path]] = None,
        create: bool = False
    ) -> Path:
        """
        Ottiene un percorso, espandendo variabili e creando directory se necessario.
        
        Args:
            key: Chiave di configurazione
            default: Valore predefinito se non trovato
            create: Se creare la directory
            
        Returns:
            Percorso
        """
        schema_default = None
        std_key = self._normalize_key(key)
        
        if std_key in self.config_schema and self.config_schema[std_key]['type'] == 'path':
            schema_default = self.config_schema[std_key].get('default')
            
        final_default = default if default is not None else schema_default
        
        path = self.get(key, final_default, lambda v: Path(os.path.expandvars(str(v))).expanduser())
        
        if create and path:
            try:
                os.makedirs(path, exist_ok=True)
                if self.debug_mode:
                    self.logger.debug(f"Directory creata: {path}")
            except Exception as e:
                self.logger.error(f"Errore creando directory {path}: {e}")
                
        return path

    def get_nested(self, key_path: str, default: Optional[T] = None) -> T:
        """
        Ottiene un valore di configurazione nidificato usando notazione a punti.
        
        Args:
            key_path: Percorso nidificato (es. "crawler.max_urls")
            default: Valore predefinito se non trovato
            
        Returns:
            Valore di configurazione nidificato
        """
        return self.get(key_path, default)
    
    def domain_to_slug(self, domain: str) -> str:
        """
        Convert a domain to a safe slug for filesystem use.
        
        Args:
            domain: Domain name or URL
            
        Returns:
            Safe slug for filesystem use
        """
        # Rimuovi protocollo e www, ed estrai solo il dominio base
        domain = domain.replace("http://", "").replace("https://", "").replace("www.", "")
        
        # Estrai solo la parte del dominio (senza path)
        domain = domain.split('/')[0]
        
        # Replace non-alphanumeric characters with underscores
        return "".join(c if c.isalnum() else "_" for c in domain)
    
    def get_all_domains(self) -> List[str]:
        """
        Ottiene tutti i domini configurati.
        
        Returns:
            Lista dei domini
        """
        return self.get_list("BASE_URLS", [])
    
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
        
        # Clean domain for directory naming
        clean_domain = domain.replace("http://", "").replace("https://", "").replace("www.", "").split('/')[0]
        
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
        
        # Alternate directory paths
        alt_root = output_root / clean_domain
        if alt_root.exists() and alt_root != domain_root:
            self.logger.info(f"Found alternate domain directory: {alt_root}")
            output_dirs = {
                "root": alt_root,
                "crawler": alt_root / "crawler_output",
                "axe": alt_root / "axe_output",
                "analysis": alt_root / "analysis_output",
                "reports": alt_root / "reports",
                "logs": alt_root / "logs",
                "charts": alt_root / "charts",
                "temp": alt_root / "temp"
            }
        
        # Create directories if needed
        if self.get_bool("CREATE_DIRS", True):
            for dir_path in output_dirs.values():
                os.makedirs(dir_path, exist_ok=True)
        
        # Crawler configuration with flexible state file paths
        crawler_config = {
            "domains": clean_domain,
            "max_urls": self.get_int("CRAWLER_MAX_URLS"),
            "max_retries": self.get_int("CRAWLER_MAX_RETRIES", 10),
            "request_delay": self.get_float("CRAWLER_REQUEST_DELAY"),
            "hybrid_mode": self.get_bool("CRAWLER_HYBRID_MODE"),
            "pending_threshold": self.get_int("CRAWLER_PENDING_THRESHOLD"),
            "max_workers": self.get_int("CRAWLER_MAX_WORKERS", min(self.cpu_count * 2, 16)),
            "output_dir": str(output_dirs["crawler"]),
            "state_file": str(output_dirs["crawler"] / f"crawler_state_{domain_slug}.pkl"),
        }
        
        # Add alternate state file paths for more robustness
        crawler_config["alternate_state_files"] = [
            str(output_dirs["crawler"] / f"crawler_state_{clean_domain}.pkl"),
            str(output_dirs["crawler"] / clean_domain / f"crawler_state_{clean_domain}.pkl"),
            str(output_root / f"crawler_state_{clean_domain}.pkl")
        ]
            
        # Configurazione di Axe analysis
        axe_config = {
            "domains": clean_domain,
            "max_templates_per_domain": self.get_int("AXE_MAX_TEMPLATES"),
            "pool_size": self.get_int("AXE_POOL_SIZE"),
            "sleep_time": self.get_float("AXE_SLEEP_TIME"),
            "headless": self.get_bool("AXE_HEADLESS"),
            "resume": self.get_bool("AXE_RESUME"),
            "excel_filename": str(output_dirs["axe"] / f"accessibility_report_{domain_slug}.xlsx"),
            "visited_file": str(output_dirs["axe"] / f"visited_urls_{domain_slug}.txt"),
            "output_folder": str(output_dirs["axe"]),
        }
        
        # Configurazione del report finale
        report_config = {
            "input_excel": str(output_dirs["axe"] / f"accessibility_report_{domain_slug}.xlsx"),
            "concat_excel": str(output_dirs["analysis"] / f"accessibility_report_{domain_slug}_concat.xlsx"),
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

    def get_pipeline_config(self) -> Dict[str, Any]:
        """
        Ottiene la configurazione specifica per la pipeline.
        
        Returns:
            Configurazione della pipeline
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
        Ottiene la configurazione del logging.
        
        Returns:
            Configurazione del logging
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
            
            # Livelli di log specifici per componente
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
        Ottiene la configurazione dell'email.
        
        Returns:
            Configurazione dell'email
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
    
    def set_debug_mode(self, enabled: bool = True) -> None:
        """
        Attiva o disattiva la modalità debug.
        
        Args:
            enabled: Se attivare la modalità debug
        """
        self.debug_mode = enabled
        if enabled:
            self.logger.setLevel(logging.DEBUG)
            self.logger.debug("Modalità debug attivata")
        else:
            self.logger.setLevel(logging.INFO)
            self.logger.info("Modalità debug disattivata")
    
    def dump_config(self) -> Dict[str, Any]:
        """
        Esporta tutta la configurazione come dizionario.
        
        Returns:
            Dizionario di tutta la configurazione
        """
        config = {
            "cli_args": self.cli_args,
            "file_config": self._file_config,
            "computed": {}
        }
        
        # Aggiungi configurazioni calcolate
        config["computed"]["output_dir"] = str(self.get_path("OUTPUT_DIR"))
        config["computed"]["base_urls"] = self.get_list("BASE_URLS")
        config["computed"]["pipeline"] = self.get_pipeline_config()
        config["computed"]["logging"] = self.get_logging_config()
        config["computed"]["email"] = self.get_email_config()
        
        # Aggiungi tutti i valori dallo schema
        for key in self.config_schema.keys():
            config["computed"][key] = self.get(key)
        
        return config
    
    def log_config_summary(self) -> None:
        """
        Logga un riepilogo della configurazione.
        """
        self.logger.info("=== Riepilogo Configurazione ===")
        self.logger.info(f"File configurazione: {self.config_file}")
        self.logger.info(f"Domini: {', '.join(self.get_all_domains())}")
        self.logger.info(f"Directory output: {self.get_path('OUTPUT_DIR')}")
        self.logger.info(f"Stadio iniziale: {self.get('START_STAGE', 'crawler')}")
        self.logger.info(f"Ripetizioni analisi Axe: {self.get_int('REPEAT_ANALYSIS', 1)}")
        self.logger.info(f"Max URL per dominio: {self.get_int('CRAWLER_MAX_URLS')}")
        self.logger.info(f"Modalità ibrida: {self.get_bool('CRAWLER_HYBRID_MODE')}")
        self.logger.info(f"Soglia Selenium: {self.get_int('CRAWLER_PENDING_THRESHOLD')}")
        self.logger.info(f"Email destinatario: {self.get('EMAIL_RECIPIENT', 'non impostato')}")
        self.logger.info("=== Fine Riepilogo ===")