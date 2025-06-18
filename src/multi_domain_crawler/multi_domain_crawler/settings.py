# -*- coding: utf-8 -*-
"""
Scrapy settings for multi_domain_crawler project with fixes for Selenium and error handling.
"""

import os
import multiprocessing
from shutil import which

# ----- BOT CONFIGURATION -----
BOT_NAME = 'multi_domain_crawler'

SPIDER_MODULES = ['multi_domain_crawler.spiders']
NEWSPIDER_MODULE = 'multi_domain_crawler.spiders'

# ----- USER AGENT E ROBOT RULES -----
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
ROBOTSTXT_OBEY = False

# ----- CONCURRENT REQUESTS -----
CONCURRENT_REQUESTS = 16  # Configurabile tramite CLI
CONCURRENT_REQUESTS_PER_DOMAIN = 8  # Configurabile tramite CLI
DOWNLOAD_DELAY = 0.5  # Configurabile tramite CLI

# Random delay (0.5 * to 1.5 * DOWNLOAD_DELAY)
RANDOMIZE_DOWNLOAD_DELAY = True

# ----- TIMEOUT -----
DOWNLOAD_TIMEOUT = 30

# ----- COOKIES -----
COOKIES_ENABLED = True
COOKIES_DEBUG = False

# ----- REDIRECT -----
REDIRECT_ENABLED = True
REDIRECT_MAX_TIMES = 10

# ----- MIDDLEWARES -----
DOWNLOADER_MIDDLEWARES = {
    # Disabilita retry middleware di default
    'scrapy.downloadermiddlewares.retry.RetryMiddleware': None,
    
    # Abilita custom retry middleware
    'multi_domain_crawler.middlewares.retry_middleware.CustomRetryMiddleware': 550,
    
    # Altri middleware standard
    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,  # Useremo headers custom
    'scrapy.downloadermiddlewares.httpauth.HttpAuthMiddleware': 300,
    'scrapy.downloadermiddlewares.downloadtimeout.DownloadTimeoutMiddleware': 350,
    'scrapy.downloadermiddlewares.defaultheaders.DefaultHeadersMiddleware': 400,
    'scrapy.downloadermiddlewares.redirect.RedirectMiddleware': 600,
    'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 810,
    'scrapy.downloadermiddlewares.cookies.CookiesMiddleware': 700,
    
    # Selenium middleware (deve essere dopo cookies ma prima di httpcompression)
    'scrapy_selenium.SeleniumMiddleware': 800,
}

SPIDER_MIDDLEWARES = {
    'scrapy.spidermiddlewares.httperror.HttpErrorMiddleware': 50,
    'scrapy.spidermiddlewares.offsite.OffsiteMiddleware': None,  # Disabilitato per multi-dominio
}

# ----- EXTENSIONS -----
EXTENSIONS = {
    'multi_domain_crawler.extensions.progress_monitor.SpiderProgressMonitor': 100,
    'scrapy.extensions.telnet.TelnetConsole': None,  # Disabilitato per sicurezza
    'scrapy.extensions.corestats.CoreStats': 0,
    'scrapy.extensions.memusage.MemoryUsage': 0,
    'scrapy.extensions.logstats.LogStats': 0,
}

# Stats collector personalizzato
STATS_CLASS = 'multi_domain_crawler.extensions.stats_collector.EnhancedStatsCollector'

# ----- PIPELINES -----
ITEM_PIPELINES = {
    'multi_domain_crawler.pipelines.domain_pipeline.MultiDomainPipeline': 300,
}

# ----- HTTP CACHE -----
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400  # 24 ore
HTTPCACHE_DIR = 'httpcache'
HTTPCACHE_IGNORE_HTTP_CODES = [500, 502, 503, 504, 400, 403, 404, 408, 429]
HTTPCACHE_STORAGE = 'scrapy.extensions.httpcache.FilesystemCacheStorage'
HTTPCACHE_POLICY = 'scrapy.extensions.httpcache.RFC2616Policy'

# ----- ERROR HANDLING -----
HTTPERROR_ALLOWED_CODES = [401, 403, 404, 429, 500]

# ----- RETRY CONFIGURATION -----
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429, 403]
RETRY_PRIORITY_ADJUST = -1
RETRY_DELAY = 1.0  # Ritardo base per retry
RETRY_DELAY_MAX = 60.0  # Ritardo massimo
RETRY_JITTER = True  # Aggiunge randomizzazione al ritardo
RETRY_SELENIUM_FALLBACK = True  # Abilita fallback a Selenium

# ----- LOGGING -----
LOG_LEVEL = 'DEBUG'
LOG_FILE = None  # Configurabile tramite CLI
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_DATEFORMAT = '%Y-%m-%d %H:%M:%S'

# Riduci verbosità di alcuni logger
import logging
logging.getLogger('selenium.webdriver.remote.remote_connection').setLevel(logging.WARNING)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
logging.getLogger('urllib3.util.retry').setLevel(logging.WARNING)
logging.getLogger('selenium.webdriver.common.service').setLevel(logging.WARNING)
logging.getLogger('selenium.webdriver.chrome.service').setLevel(logging.WARNING)
logging.getLogger('seleniumwire').setLevel(logging.WARNING)
logging.getLogger('scrapy.core.downloader.handlers.http11').setLevel(logging.INFO)
logging.getLogger('scrapy.core.scraper').setLevel(logging.INFO)

# ----- MEMORY USAGE -----
MEMUSAGE_ENABLED = True
MEMUSAGE_LIMIT_MB = 0
MEMUSAGE_WARNING_MB = 0
MEMUSAGE_NOTIFY_MAIL = []

# ----- DUPLICATE FILTER -----
DUPEFILTER_DEBUG = False
DUPEFILTER_CLASS = 'scrapy.dupefilters.RFPDupeFilter'

# ----- SELENIUM CONFIGURATION -----
SELENIUM_DRIVER_NAME = 'chrome'
SELENIUM_DRIVER_EXECUTABLE_PATH = which('chromedriver') or '/usr/local/bin/chromedriver'
SELENIUM_DRIVER_ARGUMENTS = [
    '--headless',
    '--no-sandbox', 
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-infobars',
    '--disable-blink-features=AutomationControlled',  # Evita detection
    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    '--window-size=1920,1080',
    '--start-maximized',
    '--disable-features=site-per-process',
    '--enable-features=NetworkService,NetworkServiceInProcess'
]

# Chrome options aggiuntive per evitare detection
SELENIUM_DRIVER_PREFERENCES = {
    'excludeSwitches': ['enable-automation'],
    'useAutomationExtension': False,
    'prefs': {
        'credentials_enable_service': False,
        'profile.password_manager_enabled': False,
        'profile.default_content_setting_values.notifications': 2,
        'profile.default_content_settings.popups': 0
    }
}

# Pool di driver Selenium
SELENIUM_DRIVER_POOL_SIZE = max(2, multiprocessing.cpu_count() // 2)

# ----- REQUEST FINGERPRINTING -----
# Headers di default per sembrare più umano
DEFAULT_REQUEST_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,it;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0'
}

# ----- CRAWLER SPECIFIC SETTINGS -----
OUTPUT_DIR = 'output_crawler'
JOBDIR = None  # Configurabile tramite CLI

# Limiti spider
CLOSESPIDER_PAGECOUNT = 0  # Configurabile tramite CLI
CLOSESPIDER_TIMEOUT = 0  # Configurabile tramite CLI
CLOSESPIDER_ERRORCOUNT = 0  # Configurabile tramite CLI

# ----- AUTOTHROTTLE -----
# Abilita AutoThrottle per adattare automaticamente il delay
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 60.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0
AUTOTHROTTLE_DEBUG = False

# ----- DNS -----
# Cache DNS per migliorare performance
DNSCACHE_ENABLED = True
DNSCACHE_SIZE = 10000
DNSCACHE_TIMEOUT = 60

# ----- CONNECTION POOL -----
REACTOR_THREADPOOL_MAXSIZE = 20

# ----- FEED EXPORT -----
FEED_EXPORT_ENCODING = 'utf-8'

# ----- OTHER SETTINGS -----
TELNETCONSOLE_ENABLED = False  # Disabilita per sicurezza
AJAXCRAWL_ENABLED = True  # Supporta crawling AJAX