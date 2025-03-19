# -*- coding: utf-8 -*-
"""
Middlewares per il crawler multi-dominio.
"""

from multi_domain_crawler.middlewares.hybrid_middleware import HybridDownloaderMiddleware
from multi_domain_crawler.middlewares.retry_middleware import CustomRetryMiddleware

__all__ = ['HybridDownloaderMiddleware', 'CustomRetryMiddleware']