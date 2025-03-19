# -*- coding: utf-8 -*-
"""
Estensioni per il crawler multi-dominio.
"""

from multi_domain_crawler.extensions.stats_collector import EnhancedStatsCollector
from multi_domain_crawler.extensions.progress_monitor import SpiderProgressMonitor

__all__ = ['EnhancedStatsCollector', 'SpiderProgressMonitor']