import functools
import logging
from typing import Callable, Any
import json

def log_method(func: Callable) -> Callable:
    """
    Decorator that logs method entry/exit with parameters and results.
    Also captures and logs any exceptions.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get logger from instance or module
        logger = getattr(args[0], 'logger', logging.getLogger(func.__module__))
        
        # Format arguments for logging, handling special cases
        def format_arg(arg):
            if hasattr(arg, '__dict__'):
                return arg.__class__.__name__
            try:
                return json.dumps(arg)
            except:
                return str(arg)
        
        args_repr = [format_arg(a) for a in args[1:]]
        kwargs_repr = {k: format_arg(v) for k, v in kwargs.items()}
        
        logger.debug(
            f"INIZIO {func.__qualname__} | "
            f"args: {args_repr}, kwargs: {kwargs_repr}"
        )
        
        try:
            result = func(*args, **kwargs)
            
            # Format result for logging
            result_repr = format_arg(result)
            logger.debug(
                f"FINE {func.__qualname__} | "
                f"risultato: {result_repr}"
            )
            return result
            
        except Exception as e:
            logger.exception(
                f"ERRORE in {func.__qualname__}: {str(e)}"
            )
            raise
            
    return wrapper
