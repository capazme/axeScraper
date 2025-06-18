# -*- coding: utf-8 -*-
# Define here the models for your scraped items

import scrapy
from scrapy.loader import ItemLoader
from itemloaders.processors import TakeFirst, MapCompose, Join, Identity
import html


def clean_text(text):
    """Pulisce il testo rimuovendo spazi e caratteri non necessari."""
    if text is None:
        return None
    return html.unescape(text).strip()


class PageItem(scrapy.Item):
    """Item che rappresenta una pagina web."""
    url = scrapy.Field()
    domain = scrapy.Field()
    referer = scrapy.Field()
    template = scrapy.Field()
    title = scrapy.Field()
    content = scrapy.Field()
    meta_description = scrapy.Field()
    meta_keywords = scrapy.Field()
    h1 = scrapy.Field()
    links = scrapy.Field()
    images = scrapy.Field()
    timestamp = scrapy.Field()
    status = scrapy.Field()
    status_code = scrapy.Field()
    h1_text = scrapy.Field()
    html_content = scrapy.Field()
    text_content = scrapy.Field()
    depth = scrapy.Field()
    crawl_time = scrapy.Field()


class PageItemLoader(ItemLoader):
    """Loader personalizzato per PageItem con processori predefiniti."""
    default_output_processor = TakeFirst()

    title_in = MapCompose(clean_text)
    content_in = MapCompose(clean_text)
    meta_description_in = MapCompose(clean_text)
    meta_keywords_in = MapCompose(clean_text)
    h1_in = MapCompose(clean_text)

    links_out = Identity()
    images_out = Identity()


class TemplateItem(scrapy.Item):
    """Item che rappresenta un template di URL."""
    template = scrapy.Field()
    domain = scrapy.Field()
    example_url = scrapy.Field()
    count = scrapy.Field()
    pattern = scrapy.Field()


class ErrorItem(scrapy.Item):
    """Item che rappresenta un errore di crawling."""
    url = scrapy.Field()
    domain = scrapy.Field()
    referer = scrapy.Field()
    error_type = scrapy.Field()
    error_message = scrapy.Field()
    timestamp = scrapy.Field()