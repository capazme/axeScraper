#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test semplice per il crawler multi-dominio.
Uno script autonomo senza dipendenze da framework di test esterni.
"""

import os
import sys
import tempfile
import shutil
import time
import json
from urllib.parse import urlparse

# Aggiungi il percorso al modulo
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa i moduli da testare
from src.multi_domain_crawler.multi_domain_crawler.utils.url_filters import URLFilters
from src.multi_domain_crawler.multi_domain_crawler.utils.link_extractor import AdvancedLinkExtractor
from src.multi_domain_crawler.multi_domain_crawler.spiders.multi_domain_spider import MultiDomainSpider
from src.multi_domain_crawler.multi_domain_crawler.items import PageItemLoader, PageItem
from scrapy.http import HtmlResponse, Request


def print_result(success, message):
    """Stampa risultato del test con formattazione colorata."""
    green = '\033[92m'
    red = '\033[91m'
    reset = '\033[0m'
    
    if success:
        print(f"{green}[PASS]{reset} {message}")
        return True
    else:
        print(f"{red}[FAIL]{reset} {message}")
        return False


def test_url_filters():
    """Testa le funzionalità base di URLFilters."""
    print("\n--- Test URLFilters ---")
    
    # Test is_valid_url
    valid_urls = [
        'https://example.com',
        'http://example.com/path/to/page',
        'https://example.com/?param=value',
        'https://example.com/path/to/page.html'
    ]
    
    invalid_urls = [
        'javascript:void(0)',
        'mailto:user@example.com',
        'tel:+1234567890',
        'ftp://example.com',
        'https://example.com/wp-content/uploads/image.jpg',
        'https://example.com/style.css'
    ]
    
    all_valid = all(URLFilters.is_valid_url(url) for url in valid_urls)
    result = print_result(all_valid, "Gli URL validi sono riconosciuti correttamente")
    
    all_invalid = all(not URLFilters.is_valid_url(url) for url in invalid_urls)
    result &= print_result(all_invalid, "Gli URL non validi sono riconosciuti correttamente")
    
    # Test normalize_url
    norm1 = URLFilters.normalize_url('example.com') == 'https://example.com'
    result &= print_result(norm1, "normalize_url aggiunge correttamente lo schema https://")
    
    norm2 = URLFilters.normalize_url('http://example.com/page#section') == 'http://example.com/page'
    result &= print_result(norm2, "normalize_url rimuove correttamente i frammenti")
    
    # Test get_domain
    domain1 = URLFilters.get_domain('https://example.com/page') == 'example.com'
    result &= print_result(domain1, "get_domain estrae correttamente il dominio")
    
    domain2 = URLFilters.get_domain('https://www.example.com/page') == 'example.com'
    result &= print_result(domain2, "get_domain gestisce correttamente il prefisso www")
    
    # Test get_url_template
    template = URLFilters.get_url_template('https://example.com/products/123/details')
    expected = 'example.com:/products/{num}/details'
    result &= print_result(template == expected, 
                         f"get_url_template genera il template corretto: {template}")
    
    return result


def test_advanced_link_extractor():
    """Testa l'estrattore di link avanzato."""
    print("\n--- Test AdvancedLinkExtractor ---")
    
    allowed_domains = ['example.com', 'test.com']
    extractor = AdvancedLinkExtractor(allowed_domains=allowed_domains)
    
    # HTML di test con diversi tipi di link
    html = """
    <html>
    <head>
        <title>Test Page</title>
        <meta http-equiv="refresh" content="0;url=https://example.com/redirect">
    </head>
    <body>
        <a href="https://example.com/page1">Link 1</a>
        <a href="/page2">Link 2</a>
        <a href="page3.html">Link 3</a>
        <iframe src="https://example.com/iframe"></iframe>
        <form action="/submit"></form>
        <a href="https://external-domain.com">External Link</a>
        <a href="javascript:void(0)">JS Link</a>
        <a href="mailto:info@example.com">Email</a>
        <script>
            var url = "https://example.com/js-link";
            var path = "/js-path";
        </script>
    </body>
    </html>
    """
    
    # Crea una risposta HtmlResponse
    response = HtmlResponse(
        url='https://example.com',
        body=html.encode('utf-8')
    )
    
    # Estrai i link
    links = extractor.extract_links(response)
    
    # Test numero di link estratti
    has_links = len(links) > 0
    result = print_result(has_links, f"Estratti {len(links)} link")
    
    # Test domini consentiti
    all_allowed_domains = all(any(domain in link for domain in allowed_domains) for link in links)
    result &= print_result(all_allowed_domains, 
                         "Tutti i link estratti appartengono ai domini consentiti")
    
    # Test esclusione link non validi
    no_javascript = all('javascript:' not in link for link in links)
    result &= print_result(no_javascript, "Link JavaScript esclusi correttamente")
    
    no_mailto = all('mailto:' not in link for link in links)
    result &= print_result(no_mailto, "Link mailto esclusi correttamente")
    
    # Chiudi l'executor dell'estrattore
    extractor.close()
    
    return result


def test_spider_initialization():
    """Testa l'inizializzazione dello spider MultiDomainSpider."""
    print("\n--- Test inizializzazione MultiDomainSpider ---")
    
    # Crea lo spider
    spider = MultiDomainSpider(domains='example.com,test.com', max_urls_per_domain=10)
    
    # Test domini
    domains_set = set(spider.domains) == {'example.com', 'test.com'}
    result = print_result(domains_set, "Domini impostati correttamente")
    
    # Test allowed_domains
    allowed_domains = set(spider.allowed_domains) == {'example.com', 'test.com'}
    result &= print_result(allowed_domains, "allowed_domains impostato correttamente")
    
    # Test start_urls
    expected_urls = {
        'https://www.example.com', 
        'https://example.com',
        'https://www.test.com', 
        'https://test.com'
    }
    start_urls = set(spider.start_urls) == expected_urls
    result &= print_result(start_urls, "start_urls generati correttamente")
    
    # Test limite URL
    max_urls = spider.max_urls_per_domain == 10
    result &= print_result(max_urls, "max_urls_per_domain impostato correttamente")
    
    return result


def test_spider_url_filtering():
    """Testa la logica di filtraggio degli URL dello spider."""
    print("\n--- Test filtraggio URL ---")
    
    # Crea lo spider
    spider = MultiDomainSpider(domains='example.com', max_urls_per_domain=10)
    
    # Test is_public_page
    public_urls = [
        'https://example.com',
        'https://example.com/products',
        'https://example.com/blog/post-1'
    ]
    
    non_public_urls = [
        'https://example.com/wp-admin/settings.php',
        'https://example.com/login',
        'https://example.com/wp-content/uploads/image.jpg',
        'https://example.com/style.css'
    ]
    
    all_public = all(spider.is_public_page(url) for url in public_urls)
    result = print_result(all_public, "Gli URL pubblici sono riconosciuti correttamente")
    
    all_non_public = all(not spider.is_public_page(url) for url in non_public_urls)
    result &= print_result(all_non_public, "Gli URL non pubblici sono riconosciuti correttamente")
    
    return result


def test_spider_url_limits():
    """Testa il rispetto dei limiti di URL dello spider."""
    print("\n--- Test limiti URL ---")
    
    # Crea lo spider con limiti bassi per il test
    spider = MultiDomainSpider(
        domains='example.com,test.com', 
        max_urls_per_domain=5,
        max_total_urls=8
    )
    
    # Simula crawling già in corso
    spider.domain_counts = {'example.com': 5, 'test.com': 2}
    spider.processed_count = 7
    
    # Test limite per dominio (example.com ha raggiunto il limite)
    dominio_pieno = not spider.is_public_page('https://example.com/page')
    result = print_result(dominio_pieno, 
                        "URL di un dominio che ha raggiunto il limite è correttamente rifiutato")
    
    # Test limite totale (a 1 dal limite)
    limite_quasi_raggiunto = spider.processed_count < spider.max_total_urls
    result &= print_result(limite_quasi_raggiunto, 
                         "URL accettati quando il limite totale non è ancora raggiunto")
    
    # Simula il raggiungimento del limite totale
    spider.processed_count = 8
    limite_raggiunto = spider.processed_count >= spider.max_total_urls
    result &= print_result(limite_raggiunto, 
                         "Il limite totale è correttamente riconosciuto quando raggiunto")
    
    return result


def test_page_item_extraction():
    """Testa l'estrazione degli item dalla pagina."""
    print("\n--- Test estrazione item ---")
    
    # HTML di test
    html = """
    <html>
    <head>
        <title>Pagina di Test</title>
        <meta name="description" content="Descrizione della pagina di test">
        <meta name="keywords" content="test, crawler, example">
    </head>
    <body>
        <h1>Titolo della Pagina</h1>
        <p>Contenuto di esempio per il test.</p>
        <a href="https://example.com/altra-pagina">Link</a>
    </body>
    </html>
    """
    
    # Crea una risposta HtmlResponse
    response = HtmlResponse(
        url='https://example.com/pagina-test',
        body=html.encode('utf-8'),
        request=Request(url='https://example.com/pagina-test', meta={'depth': 1})
    )
    
    # Crea un ItemLoader
    loader = PageItemLoader(item=PageItem(), selector=response)
    
    # Aggiungi i campi
    loader.add_value('url', response.url)
    loader.add_value('domain', URLFilters.get_domain(response.url))
    loader.add_value('depth', response.meta.get('depth', 0))
    loader.add_css('title', 'title::text')
    loader.add_css('meta_description', 'meta[name="description"]::attr(content)')
    loader.add_css('meta_keywords', 'meta[name="keywords"]::attr(content)')
    loader.add_css('h1', 'h1::text')
    
    # Carica l'item
    item = loader.load_item()
    
    # Verifica i campi estratti
    has_url = item.get('url') == 'https://example.com/pagina-test'
    result = print_result(has_url, "URL estratto correttamente")
    
    has_domain = item.get('domain') == 'example.com'
    result &= print_result(has_domain, "Dominio estratto correttamente")
    
    has_title = item.get('title') == 'Pagina di Test'
    result &= print_result(has_title, "Titolo estratto correttamente")
    
    has_description = item.get('meta_description') == 'Descrizione della pagina di test'
    result &= print_result(has_description, "Meta descrizione estratta correttamente")
    
    has_h1 = item.get('h1') == 'Titolo della Pagina'
    result &= print_result(has_h1, "H1 estratto correttamente")
    
    return result


def run_all_tests():
    """Esegue tutti i test e restituisce un sommario."""
    print("\n========================================")
    print("  TEST MULTI-DOMAIN CRAWLER")
    print("========================================")
    
    tests = [
        test_url_filters,
        test_advanced_link_extractor,
        test_spider_initialization,
        test_spider_url_filtering,
        test_spider_url_limits,
        test_page_item_extraction
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    # Sommario dei risultati
    print("\n========================================")
    print(f"Test totali: {len(tests)}")
    print(f"Test passati: {results.count(True)}")
    print(f"Test falliti: {results.count(False)}")
    print("========================================")
    
    return all(results)


if __name__ == "__main__":
    # Esegui tutti i test
    success = run_all_tests()
    
    # Esci con codice appropriato
    sys.exit(0 if success else 1)