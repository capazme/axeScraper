# -*- coding: utf-8 -*-
"""
Configurazioni specifiche per siti protetti da Cloudflare.
Usa queste impostazioni quando incontri protezioni anti-bot.
"""

from multi_domain_crawler.settings import *

# Override delle impostazioni base per Cloudflare

# ----- CLOUDFLARE BYPASS SETTINGS -----

# Disabilita robots.txt che spesso è bloccato
ROBOTSTXT_OBEY = False

# Riduci drasticamente la concorrenza
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1

# Aumenta i delay
DOWNLOAD_DELAY = 5  # 5 secondi tra richieste
RANDOMIZE_DOWNLOAD_DELAY = True  # Varia tra 2.5 e 7.5 secondi

# Timeout più lungo per Selenium
DOWNLOAD_TIMEOUT = 60

# ----- RETRY CONFIGURATION -----
RETRY_TIMES = 5  # Più tentativi
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429, 403, 520, 521, 522, 523, 524]  # Includi errori Cloudflare
RETRY_DELAY = 3.0
RETRY_DELAY_MAX = 120.0

# ----- SELENIUM CONFIGURATION -----
SELENIUM_DRIVER_ARGUMENTS = [
    '--headless',
    '--no-sandbox',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--disable-setuid-sandbox',
    '--disable-features=VizDisplayCompositor',
    '--disable-blink-features=AutomationControlled',
    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    '--window-size=1920,1080',
    '--start-maximized',
    '--disable-extensions',
    '--disable-plugins',
    '--disable-images',
    '--disable-javascript',  # Rimuovi se il sito richiede JS
    '--incognito',
    '--disable-web-security',
    '--disable-features=IsolateOrigins,site-per-process',
    '--disable-site-isolation-trials',
    '--no-first-run',
    '--no-default-browser-check',
    '--no-sandbox-flag',
]

# Preferenze Chrome aggiuntive
SELENIUM_DRIVER_PREFERENCES = {
    'excludeSwitches': ['enable-automation', 'enable-logging'],
    'useAutomationExtension': False,
    'prefs': {
        'credentials_enable_service': False,
        'profile.password_manager_enabled': False,
        'profile.default_content_setting_values.notifications': 2,
        'profile.default_content_settings.popups': 0,
        'profile.managed_default_content_settings.images': 2,  # Disabilita immagini
        'permissions.default.stylesheet': 2,  # Disabilita CSS se possibile
    }
}

# ----- AUTOTHROTTLE CLOUDFLARE -----
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 120
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5  # Molto conservativo
AUTOTHROTTLE_DEBUG = True

# ----- MIDDLEWARE CLOUDFLARE -----
DOWNLOADER_MIDDLEWARES.update({
    # Aggiungi un middleware per rotazione headers
    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
    'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
})

# ----- USER AGENTS POOL -----
USER_AGENT_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0',
]

# ----- HEADERS CLOUDFLARE -----
DEFAULT_REQUEST_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

# ----- CACHE DISABLED FOR CLOUDFLARE -----
HTTPCACHE_ENABLED = False  # Disabilita cache per evitare risposte cached con challenge

# ----- COOKIES -----
COOKIES_ENABLED = True
COOKIES_DEBUG = True

# ----- DNS CACHE -----
DNSCACHE_ENABLED = True
DNSCACHE_SIZE = 10000
DNSCACHE_TIMEOUT = 60

# ----- DOWNLOAD HANDLERS -----
DOWNLOAD_HANDLERS = {
    'http': 'scrapy.core.downloader.handlers.http.HTTPDownloadHandler',
    'https': 'scrapy.core.downloader.handlers.http.HTTPDownloadHandler',
}

# ----- LOG LEVEL -----
LOG_LEVEL = 'INFO'  # Riduci log per performance

# ----- CUSTOM SETTINGS PER SPIDER -----
# Usa nel tuo spider:
# custom_settings = {
#     'SELENIUM_THRESHOLD': 999,  # Usa sempre Selenium
#     'HYBRID_MODE': True,
#     'REQUEST_DELAY': 5.0,
# }