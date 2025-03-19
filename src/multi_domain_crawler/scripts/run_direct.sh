#!/bin/bash

# Domains con virgolette doppie per preservare le virgole
scrapy crawl multi_domain_spider \
  -a domains="iper.it,esselunga.it" \
  -a max_urls_per_domain=50 \
  -a hybrid_mode=False \
  -s CONCURRENT_REQUESTS=16 \
  -s CONCURRENT_REQUESTS_PER_DOMAIN=8 \
  -s OUTPUT_DIR=output_crawler \
  -s LOG_LEVEL=DEBUG \
  -s HTTPCACHE_ENABLED=False \
  -s DUPEFILTER_DEBUG=True \
  --nolog  # Mostra output direttamente nella console