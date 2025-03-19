# -*- coding: utf-8 -*-
# Settings per il crawler multi-dominio

import os
import multiprocessing
from shutil import which

# ----- IMPOSTAZIONI BASE -----
BOT_NAME = 'multi_domain_crawler'

SPIDER_MODULES = ['multi_domain_crawler.spiders']
NEWSPIDER_MODULE = 'multi_domain_crawler.spiders'

# ----- USER AGENT -----
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36'

# ----- IMPOSTAZIONI ROBOTS.TXT -----
ROBOTSTXT_OBEY = False  # Configurabile tramite CLI

# ----- CONCORRENZA E PERFORMANCE -----
# Calcolo automatico basato sulle risorse del sistema
CONCURRENT_REQUESTS = min(multiprocessing.cpu_count() * 2, 32)
CONCURRENT_REQUESTS_PER_DOMAIN = min(multiprocessing.cpu_count(), 16)
CONCURRENT_REQUESTS_PER_IP = 0  # Usa il limite per dominio

# Download e processing settings
DOWNLOAD_DELAY = 0.25  # Configurabile tramite CLI
DOWNLOAD_TIMEOUT = 60
RANDOMIZE_DOWNLOAD_DELAY = True

# Parallelizzazione e threading
REACTOR_THREADPOOL_MAXSIZE = 20
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'

# ----- MIDDLEWARE -----
DOWNLOADER_MIDDLEWARES = {
    # Custom middleware
    'multi_domain_crawler.middlewares.hybrid_middleware.HybridDownloaderMiddleware': 543,
    'multi_domain_crawler.middlewares.retry_middleware.CustomRetryMiddleware': 550,
    
    # Scrapy built-in
    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
    'scrapy.downloadermiddlewares.retry.RetryMiddleware': None,  # Sostituito da CustomRetryMiddleware
    'scrapy.downloadermiddlewares.redirect.RedirectMiddleware': 600,
    'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 810,
    'scrapy.downloadermiddlewares.cookies.CookiesMiddleware': 700,
    
    # Selenium middleware
    'scrapy_selenium.SeleniumMiddleware': 800,
}

SPIDER_MIDDLEWARES = {
    'scrapy.spidermiddlewares.httperror.HttpErrorMiddleware': 50,
    'scrapy.spidermiddlewares.offsite.OffsiteMiddleware': None,  # Disabilitato per gestire multi-dominio
}

# ----- ESTENSIONI -----
EXTENSIONS = {
    'multi_domain_crawler.extensions.progress_monitor.SpiderProgressMonitor': 100,
    'scrapy.extensions.telnet.TelnetConsole': None,  # Disabilitato per sicurezza
    'scrapy.extensions.corestats.CoreStats': 0,
    'scrapy.extensions.memusage.MemoryUsage': 0,
    'scrapy.extensions.logstats.LogStats': 0,
}

# Sostituisce il collettore di statistiche standard
STATS_CLASS = 'multi_domain_crawler.extensions.stats_collector.EnhancedStatsCollector'

# ----- PIPELINE -----
ITEM_PIPELINES = {
    'multi_domain_crawler.pipelines.domain_pipeline.MultiDomainPipeline': 300,
}

# ----- CACHE HTTP -----
HTTPCACHE_ENABLED = True  # Configurabile tramite CLI
HTTPCACHE_EXPIRATION_SECS = 86400  # 24 ore
HTTPCACHE_DIR = 'httpcache'
HTTPCACHE_IGNORE_HTTP_CODES = [500, 502, 503, 504, 400, 403, 404, 408]
HTTPCACHE_STORAGE = 'scrapy.extensions.httpcache.FilesystemCacheStorage'
HTTPCACHE_POLICY = 'scrapy.extensions.httpcache.RFC2616Policy'
HTTPERROR_ALLOWED_CODES = [401, 403, 404, 500]

# ----- RETRY -----
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429, 403]
RETRY_PRIORITY_ADJUST = -1

# ----- LOGGING -----
LOG_LEVEL = 'INFO'  # Configurabile tramite CLI
LOG_FILE = None  # Configurabile tramite CLI

# Formattazione dei log
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_DATEFORMAT = '%Y-%m-%d %H:%M:%S'

# ----- METRICHE E MONITORAGGIO -----
MEMUSAGE_ENABLED = True
MEMUSAGE_LIMIT_MB = 0
MEMUSAGE_WARNING_MB = 0
MEMUSAGE_NOTIFY_MAIL = []

# Attiva debug per filtro duplicati (solo in development)
DUPEFILTER_DEBUG = False

# ----- SELENIUM CONFIGURATION -----
SELENIUM_DRIVER_NAME = 'chrome'
SELENIUM_DRIVER_EXECUTABLE_PATH = which('chromedriver')
SELENIUM_DRIVER_ARGUMENTS = [
    '--headless', 
    '--no-sandbox',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-infobars',
    '--blink-settings=imagesEnabled=false',
    '--disable-features=site-per-process',
]

# Dimensione del pool di driver Selenium
SELENIUM_DRIVER_POOL_SIZE = max(2, multiprocessing.cpu_count() // 2)

# ----- IMPOSTAZIONI SPECIFICHE CRAWLER -----
# Directory per output del crawler
OUTPUT_DIR = 'output_crawler'

# Directory per persistenza job (riprendere crawling interrotti)
JOBDIR = None  # Configurabile tramite CLI

# Limite per chiusura spider
CLOSESPIDER_PAGECOUNT = 0  # Configurabile tramite CLI
CLOSESPIDER_TIMEOUT = 0  # Configurabile tramite CLI
CLOSESPIDER_ERRORCOUNT = 0  # Configurabile tramite CLI