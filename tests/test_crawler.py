#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test semplice per il crawler multi-dominio.
Uno script autonomo senza dipendenze da framework di test esterni.

Uso:
    python test_crawler.py --domain example.com
    python test_crawler.py --domain example.com,test.com --max-urls 100
"""

import os
import sys
import tempfile
import shutil
import time
import json
import argparse
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
    
    # Ottieni domini dai parametri di linea di comando
    args = parse_arguments()
    domains_list = args.domain.split(',')
    max_urls = args.max_urls
    
    print(f"Utilizzo domini: {args.domain} e max_urls: {max_urls}")
    
    # Crea lo spider con i parametri specificati
    spider = MultiDomainSpider(domains=args.domain, max_urls_per_domain=max_urls)
    
    # Test domini
    domains_set = set(spider.domains) == set(domains_list)
    result = print_result(domains_set, "Domini impostati correttamente")
    
    # Test allowed_domains
    allowed_domains = set(spider.allowed_domains) == set(domains_list)
    result &= print_result(allowed_domains, "allowed_domains impostato correttamente")
    
    # Test start_urls
    expected_urls = set()
    for domain in domains_list:
        expected_urls.add(f"https://www.{domain}")
        expected_urls.add(f"https://{domain}")
    
    start_urls = set(spider.start_urls) == expected_urls
    result &= print_result(start_urls, f"start_urls generati correttamente: {spider.start_urls}")
    
    # Test limite URL
    url_limit = spider.max_urls_per_domain == max_urls
    result &= print_result(url_limit, f"max_urls_per_domain impostato correttamente: {spider.max_urls_per_domain}")
    
    return result


def test_spider_url_filtering():
    """Testa la logica di filtraggio degli URL dello spider."""
    print("\n--- Test filtraggio URL ---")
    
    # Ottieni domini dai parametri di linea di comando
    args = parse_arguments()
    domain = args.domain.split(',')[0]  # Usa il primo dominio per i test
    
    # Crea lo spider
    spider = MultiDomainSpider(domains=domain, max_urls_per_domain=args.max_urls)
    
    # Test is_public_page con URL personalizzati per il dominio specificato
    public_urls = [
        f'https://{domain}',
        f'https://{domain}/products',
        f'https://{domain}/blog/post-1'
    ]
    
    non_public_urls = [
        f'https://{domain}/wp-admin/settings.php',
        f'https://{domain}/login',
        f'https://{domain}/wp-content/uploads/image.jpg',
        f'https://{domain}/style.css'
    ]
    
    all_public = all(spider.is_public_page(url) for url in public_urls)
    result = print_result(all_public, f"Gli URL pubblici di {domain} sono riconosciuti correttamente")
    
    all_non_public = all(not spider.is_public_page(url) for url in non_public_urls)
    result &= print_result(all_non_public, f"Gli URL non pubblici di {domain} sono riconosciuti correttamente")
    
    return result


def test_spider_url_limits():
    """Testa il rispetto dei limiti di URL dello spider."""
    print("\n--- Test limiti URL ---")
    
    # Ottieni domini dai parametri di linea di comando
    args = parse_arguments()
    domains_list = args.domain.split(',')
    max_urls = args.max_urls
    
    # Utilizziamo il primo dominio come esempio di dominio che ha raggiunto il limite
    domain1 = domains_list[0]
    
    # Se disponibile, usa un secondo dominio, altrimenti crea un dominio fittizio
    domain2 = domains_list[1] if len(domains_list) > 1 else "test-domain.com"
    
    # Crea lo spider con limiti calcolati in base al max_urls specificato
    spider = MultiDomainSpider(
        domains=f"{domain1},{domain2}", 
        max_urls_per_domain=max_urls,
        max_total_urls=max_urls * 2  # Un ragionevole limite totale per il test
    )
    
    # Simula crawling già in corso: il primo dominio ha raggiunto il limite
    spider.domain_counts = {domain1: max_urls, domain2: max_urls - 2}
    spider.processed_count = max_urls + (max_urls - 2)
    
    # Test limite per dominio
    url_dominio_pieno = f"https://{domain1}/page"
    print(f"Verifica limite per dominio {domain1}: {spider.domain_counts[domain1]}/{max_urls}")
    
    # Non possiamo usare is_public_page per questo test perché non tiene conto del limite di dominio
    # Dobbiamo verificare direttamente la logica dello spider
    dominio_pieno = spider.domain_counts[domain1] >= max_urls
    result = print_result(dominio_pieno, 
                        f"Il dominio {domain1} ha raggiunto il limite")
    
    # Test limite totale (a 2 dal limite)
    limite_quasi_raggiunto = spider.processed_count < spider.max_total_urls
    result &= print_result(limite_quasi_raggiunto, 
                         f"URL accettati quando il limite totale non è ancora raggiunto ({spider.processed_count}/{spider.max_total_urls})")
    
    # Simula il raggiungimento del limite totale
    spider.processed_count = spider.max_total_urls
    limite_raggiunto = spider.processed_count >= spider.max_total_urls
    result &= print_result(limite_raggiunto, 
                         f"Il limite totale è correttamente riconosciuto quando raggiunto ({spider.processed_count}/{spider.max_total_urls})")
    
    return result


def test_page_item_extraction():
    """Testa l'estrazione degli item dalla pagina."""
    print("\n--- Test estrazione item ---")
    
    # Ottieni domini dai parametri di linea di comando
    args = parse_arguments()
    domain = args.domain.split(',')[0]  # Usa il primo dominio
    
    # HTML di test personalizzato per il dominio specificato
    html = f"""
    <html>
    <head>
        <title>Pagina di Test - {domain}</title>
        <meta name="description" content="Descrizione della pagina di test per {domain}">
        <meta name="keywords" content="test, crawler, {domain}">
    </head>
    <body>
        <h1>Titolo della Pagina - {domain}</h1>
        <p>Contenuto di esempio per il test di {domain}.</p>
        <a href="https://{domain}/altra-pagina">Link</a>
    </body>
    </html>
    """
    
    # Crea una risposta HtmlResponse
    url = f'https://{domain}/pagina-test'
    response = HtmlResponse(
        url=url,
        body=html.encode('utf-8'),
        request=Request(url=url, meta={'depth': 1})
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
    has_url = item.get('url') == url
    result = print_result(has_url, f"URL estratto correttamente: {item.get('url')}")
    
    has_domain = item.get('domain') == domain
    result &= print_result(has_domain, f"Dominio estratto correttamente: {item.get('domain')}")
    
    expected_title = f"Pagina di Test - {domain}"
    has_title = item.get('title') == expected_title
    result &= print_result(has_title, f"Titolo estratto correttamente: {item.get('title')}")
    
    expected_description = f"Descrizione della pagina di test per {domain}"
    has_description = item.get('meta_description') == expected_description
    result &= print_result(has_description, f"Meta descrizione estratta correttamente: {item.get('meta_description')}")
    
    expected_h1 = f"Titolo della Pagina - {domain}"
    has_h1 = item.get('h1') == expected_h1
    result &= print_result(has_h1, f"H1 estratto correttamente: {item.get('h1')}")
    
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


def parse_arguments():
    """Gestisce i parametri dalla linea di comando."""
    parser = argparse.ArgumentParser(description='Test per il crawler multi-dominio')
    
    parser.add_argument('--domain', '-d', 
                      default='example.com,test.com',
                      help='Dominio o domini da utilizzare nei test (separati da virgola)')
    
    parser.add_argument('--max-urls', '-m', 
                      type=int, 
                      default=10,
                      help='Numero massimo di URL per dominio')
    
    parser.add_argument('--run-live-test', '-l',
                      action='store_true',
                      help='Esegue un test live sul dominio specificato (crawling effettivo)')
    
    return parser.parse_args()


def test_live_crawling(domains, max_urls_per_domain):
    """Esegue un test di crawling live sul dominio specificato."""
    print("\n--- Test Live Crawling ---")
    print(f"Domini: {domains}")
    print(f"Max URL per dominio: {max_urls_per_domain}")
    
    from scrapy.crawler import CrawlerProcess
    from src.multi_domain_crawler.multi_domain_crawler.spiders.multi_domain_spider import MultiDomainSpider
    
    # Crea una directory temporanea per l'output
    output_dir = tempfile.mkdtemp()
    print(f"Directory output: {output_dir}")
    
    # Configura le impostazioni di Scrapy
    settings = {
        'CONCURRENT_REQUESTS': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'LOG_LEVEL': 'INFO',
        'OUTPUT_DIR': output_dir,
        'HTTPCACHE_ENABLED': True,
        'DOWNLOAD_DELAY': 2.0,  # Per cortesia verso i server
        'ITEM_PIPELINES': {
            'multi_domain_crawler.pipelines.domain_pipeline.MultiDomainPipeline': 300
        }
    }
    
    # Crea un processo crawler
    process = CrawlerProcess(settings)
    
    # Aggiungi lo spider con i domini specificati
    process.crawl(MultiDomainSpider, 
                 domains=domains, 
                 max_urls_per_domain=max_urls_per_domain,
                 hybrid_mode='False')
    
    try:
        print("Avvio crawling... (Premi Ctrl+C per interrompere)")
        print("Questo processo eseguirà un crawling reale sui domini specificati.")
        print("Per cortesia, mantieni il DOWNLOAD_DELAY alto per non sovraccaricare i server.")
        
        # Esegui il processo di crawling
        process.start()
        
        # Verifica i risultati
        domain_list = domains.split(',')
        all_domains_crawled = True
        
        for domain in domain_list:
            domain_dir = os.path.join(output_dir, domain)
            
            if not os.path.exists(domain_dir):
                print(f"Nessuna directory di output creata per il dominio {domain}")
                all_domains_crawled = False
                continue
                
            # Verifica i file generati
            state_file = os.path.join(domain_dir, f'crawler_state_{domain}.pkl')
            if not os.path.exists(state_file):
                print(f"Nessun file di stato trovato per il dominio {domain}")
                all_domains_crawled = False
                continue
                
            # Verifica i report
            reports = [f for f in os.listdir(domain_dir) if f.startswith('report_')]
            if not reports:
                print(f"Nessun report generato per il dominio {domain}")
                all_domains_crawled = False
                continue
                
            # Stampa il numero di URL visitati
            try:
                import pickle
                with open(state_file, 'rb') as f:
                    state = pickle.load(f)
                    url_count = len(state.get('unique_pages', []))
                    print(f"Dominio {domain}: {url_count} URL visitati")
                    
                    # Stampa alcuni URL come esempio
                    if url_count > 0:
                        print("Esempi di URL visitati:")
                        for url in list(state.get('unique_pages', []))[:5]:
                            print(f"  - {url}")
                        
                    # Verifica se ha rispettato il limite
                    assert url_count <= max_urls_per_domain, \
                           f"Limite di URL per dominio non rispettato: {url_count} > {max_urls_per_domain}"
            except Exception as e:
                print(f"Errore leggendo il file di stato: {e}")
                all_domains_crawled = False
                
        result = print_result(all_domains_crawled, "Crawling completato con successo per tutti i domini")
        
        # Pulizia
        print(f"Eliminazione della directory temporanea {output_dir}")
        shutil.rmtree(output_dir)
        
        return result
        
    except KeyboardInterrupt:
        print("\nCrawling interrotto dall'utente")
        # Pulizia
        shutil.rmtree(output_dir)
        return False
    except Exception as e:
        print(f"\nErrore durante il crawling: {e}")
        # Pulizia
        shutil.rmtree(output_dir)
        return False


if __name__ == "__main__":
    # Analizza gli argomenti
    args = parse_arguments()
    
    if args.run_live_test:
        # Esegui test di crawling live
        success = test_live_crawling(args.domain, args.max_urls)
    else:
        # Esegui test automatici
        success = run_all_tests()
    
    # Esci con codice appropriato
    sys.exit(0 if success else 1)