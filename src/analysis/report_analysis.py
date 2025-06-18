#!/usr/bin/env python3
"""
Enhanced Accessibility Analysis Module V2

Processes data from accessibility tests, generates visualizations,
and creates comprehensive reports with actionable recommendations.
Handles optional crawler data and prioritizes '_concat' input files.
"""

import os
import logging
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from datetime import datetime
import pickle
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json

# Import configuration management (ensure these paths are correct in your project)
try:
    from utils.config_manager import ConfigurationManager
    from utils.logging_config import get_logger
    from utils.output_manager import OutputManager
except ImportError:
    # Provide basic fallbacks if utils are not found (for standalone execution)
    print("Warning: utils not found. Using basic logging and path handling.")
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    def get_logger(name, config=None, output_manager=None):
        return logging.getLogger(name)
    class OutputManager:
        def __init__(self, base_dir, domain, create_dirs=False):
            self.base_dir = Path(base_dir)
            self.domain = domain
            self.domain_slug = re.sub(r'[^\w\-]+', '_', domain.lower())
            self.paths = {
                "base": self.base_dir / self.domain_slug,
                "axe": self.base_dir / self.domain_slug / "axe",
                "crawler": self.base_dir / self.domain_slug / "crawler",
                "analysis": self.base_dir / self.domain_slug / "analysis",
                "charts": self.base_dir / self.domain_slug / "analysis" / "charts",
            }
            if create_dirs:
                for path in self.paths.values():
                    path.mkdir(parents=True, exist_ok=True)
        def get_path(self, key, filename=None):
            path = self.paths.get(key, self.paths["base"])
            return path / filename if filename else path
        def backup_existing_file(self, key, filename):
             # Dummy implementation
             return None
    class ConfigurationManager:
        def __init__(self, project_name="axeScraper"): pass
        def get_logging_config(self): return {"components": {"report_analysis": {}}}
        def get_int(self, key, default): return default
        def get_path(self, key, default): return default
        def load_domain_config(self, domain): return {}

# --- Configuration (Moved from __init__) ---
# Ideally, load these from a config file using ConfigurationManager
# For simplicity here, defined as module-level constants.

IMPACT_WEIGHTS = {
    'critical': 4,
    'serious': 3,
    'moderate': 2,
    'minor': 1,
    'unknown': 0
}

WCAG_CATEGORIES = {
    # --- Principio 1: Perceivable ---
    'image-alt': {'category': 'Perceivable', 'criterion': '1.1.1', 'name': 'Non-text Content'},
    'list': {'category': 'Perceivable', 'criterion': '1.3.1', 'name': 'Info and Relationships'},
    'heading-order': {'category': 'Perceivable', 'criterion': '1.3.1', 'name': 'Info and Relationships'},
    'color-contrast': {'category': 'Perceivable', 'criterion': '1.4.3', 'name': 'Contrast (Minimum)'},
    'meta-viewport': {'category': 'Perceivable', 'criterion': '1.4.4', 'name': 'Resize text'},
    'reflow': {'category': 'Perceivable', 'criterion': '1.4.10', 'name': 'Reflow'},
    'non-text-contrast': {'category': 'Perceivable', 'criterion': '1.4.11', 'name': 'Non-text Contrast'},

    # --- Principio 2: Operable ---
    'keyboard': {'category': 'Operable', 'criterion': '2.1.1', 'name': 'Keyboard'},
    'bypass': {'category': 'Operable', 'criterion': '2.4.1', 'name': 'Bypass Blocks'},
    'document-title': {'category': 'Operable', 'criterion': '2.4.2', 'name': 'Page Titled'},
    'link-name': {'category': 'Operable', 'criterion': '2.4.4', 'name': 'Link Purpose (In Context)'},
    'empty-heading': {'category': 'Operable', 'criterion': '2.4.6', 'name': 'Headings and Labels'},
    'focus-visible': {'category': 'Operable', 'criterion': '2.4.7', 'name': 'Focus Visible'},
    'target-size': {'category': 'Operable', 'criterion': '2.5.8', 'name': 'Target Size (Minimum)'},

    # --- Principio 3: Understandable ---
    'html-has-lang': {'category': 'Understandable', 'criterion': '3.1.1', 'name': 'Language of Page'},
    'html-lang-valid': {'category': 'Understandable', 'criterion': '3.1.2', 'name': 'Language of Parts'},
    'label': {'category': 'Understandable', 'criterion': '3.3.2', 'name': 'Labels or Instructions'},
    'form-field-multiple-labels': {'category': 'Understandable', 'criterion': '3.3.2', 'name': 'Labels or Instructions'},

    # --- Principio 4: Robust ---
    'aria-roles': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
    'aria-allowed-attr': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
    'button-name': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
    'frame-title': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
    'aria-required-children': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
    'aria-required-parent': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},

    # NOTA: il criterio 4.1.1 Parsing è obsoleto in WCAG 2.2.
    # Errori come ID duplicati ora violano il 4.1.2 perché impediscono
    # la determinazione univoca del nome/ruolo/valore di un elemento.
    'duplicate-id-active': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
    'duplicate-id-aria': {'category': 'Robust', 'criterion': '4.1.2', 'name': 'Name, Role, Value'},
    
    'status-messages': {'category': 'Robust', 'criterion': '4.1.3', 'name': 'Status Messages'},
}

SOLUTION_MAPPING = {
    # Perceivable
    '1.1.1_non-text-content': {'description': 'Provide text alternatives for non-text content.', 'technical': 'Use the `alt` attribute for images. For complex images, provide a longer description nearby. For decorative images, use `alt=""`.', 'impact': 'Users of screen readers, people with slow connections, or those who have images disabled.'},
    '1.2.1_audio-only-video-only-prerecorded': {'description': 'Provide an alternative for prerecorded audio-only and video-only media.', 'technical': 'Provide a full text transcript for audio-only content. For video-only, provide a text transcript or an audio track.', 'impact': 'Users who are deaf or hard of hearing (for audio), and users who are blind (for video).'},
    '1.2.2_captions-prerecorded': {'description': 'Provide captions for all prerecorded audio content in synchronized media.', 'technical': 'Add a synchronized caption track (e.g., WebVTT) to all videos containing audio.', 'impact': 'Users who are deaf, hard of hearing, or watching in a noisy environment.'},
    '1.2.3_audio-description-media-alternative-prerecorded': {'description': 'Provide audio description or a full text alternative for prerecorded video content.', 'technical': 'Add a synchronized audio description track or provide a detailed text transcript that includes all visual information.', 'impact': 'Users who are blind or have low vision.'},
    '1.2.4_captions-live': {'description': 'Provide captions for all live audio content in synchronized media.', 'technical': 'Use real-time captioning services (e.g., CART) for live streams and webcasts.', 'impact': 'Users who are deaf or hard of hearing participating in live events.'},
    '1.2.5_audio-description-prerecorded': {'description': 'Provide audio description for all prerecorded video content.', 'technical': 'Add a synchronized audio description track to all videos.', 'impact': 'Users who are blind or have low vision.'},
    '1.2.6_sign-language-prerecorded': {'description': 'Provide sign language interpretation for all prerecorded audio content.', 'technical': 'Embed a video of a sign language interpreter into the main video content.', 'impact': 'Users whose primary language is sign language.'},
    '1.2.7_extended-audio-description-prerecorded': {'description': 'Provide extended audio descriptions where pauses in video are insufficient.', 'technical': 'When needed, pause the video to allow for a longer, more detailed audio description to be delivered.', 'impact': 'Users who are blind, for understanding complex visual scenes.'},
    '1.2.8_media-alternative-prerecorded': {'description': 'Provide a media alternative for all prerecorded synchronized media.', 'technical': 'Provide a single document with a full text transcript, including all visual and auditory information.', 'impact': 'Users with both vision and hearing impairments.'},
    '1.2.9_audio-only-live': {'description': 'Provide an alternative for live audio-only content.', 'technical': 'Provide a real-time text-based stream, like CART, alongside the live audio.', 'impact': 'Users who are deaf or hard of hearing.'},
    '1.3.1_info-and-relationships': {'description': 'Ensure information, structure, and relationships conveyed through presentation are programmatically determinable.', 'technical': 'Use semantic HTML: `<h1>`-`<h6>` for headings, `<ul>`/`<ol>`/`<li>` for lists, `<table>` for data tables, `aria-roles` for custom components.', 'impact': 'Screen reader users who rely on programmatic structure to understand the page layout and relationships between elements.'},
    '1.3.2_meaningful-sequence': {'description': 'Ensure the reading and navigation order is logical and intuitive.', 'technical': 'Structure the source code (DOM order) to match the logical flow of content. Avoid relying on CSS positioning to reorder content visually.', 'impact': 'Keyboard and screen reader users who navigate the page sequentially.'},
    '1.3.3_sensory-characteristics': {'description': 'Do not rely solely on sensory characteristics like shape, size, or color for instructions.', 'technical': 'Provide text labels in addition to visual cues. E.g., "Press the red, circular button on the right" should be "Press the \'Submit\' button".', 'impact': 'Users who are blind or have color vision deficiencies.'},
    '1.3.4_orientation': {'description': 'Do not restrict content to a single display orientation, such as portrait or landscape.', 'technical': 'Use responsive design techniques to ensure the layout adapts to both portrait and landscape modes. Avoid locking the orientation.', 'impact': 'Users with disabilities who have their devices mounted in a fixed orientation.'},
    '1.3.5_identify-input-purpose': {'description': 'Programmatically identify the purpose of input fields.', 'technical': 'Use the `autocomplete` attribute on form fields with appropriate values (e.g., `autocomplete="name"`, `autocomplete="email"`).', 'impact': 'Users with cognitive disabilities who benefit from autofill, and assistive technologies that can apply custom icons or help.'},
    '1.3.6_identify-purpose': {'description': 'Programmatically identify the purpose of UI components, icons, and regions.', 'technical': 'Use ARIA landmark roles (`<nav>`, `<main>`), ARIA attributes, or other technologies to define the purpose of regions and components.', 'impact': 'Screen reader users who can navigate by landmarks and understand the purpose of different page sections.'},
    '1.4.1_use-of-color': {'description': 'Color is not used as the only visual means of conveying information.', 'technical': 'Supplement color cues with text, icons, or patterns. E.g., for an error field, add an icon and text message, not just a red border.', 'impact': 'Users with color vision deficiencies.'},
    '1.4.2_audio-control': {'description': 'Provide a mechanism to control audio that plays automatically for more than 3 seconds.', 'technical': 'If audio autoplays, provide a visible and keyboard-accessible pause/stop button or volume control.', 'impact': 'Screen reader users whose screen reader audio would be obscured by the website\'s audio.'},
    '1.4.3_contrast-minimum': {'description': 'Ensure text has sufficient color contrast against its background.', 'technical': 'Ensure text meets a 4.5:1 contrast ratio (3:1 for large text) using a color contrast checker tool.', 'impact': 'Users with low vision or color vision deficiencies.'},
    '1.4.4_resize-text': {'description': 'Ensure text can be resized up to 200% without loss of content or functionality.', 'technical': 'Use relative units (em, rem, %) for text and container sizes. Avoid fixed-height containers for text.', 'impact': 'Users with low vision who need to magnify text to read it.'},
    '1.4.5_images-of-text': {'description': 'Use real text instead of images of text whenever possible.', 'technical': 'Use CSS for styling text. If an image of text is unavoidable (e.g., a logo), ensure its `alt` text matches the text in the image.', 'impact': 'Users with low vision who need to resize text and customize its appearance.'},
    '1.4.6_contrast-enhanced': {'description': 'Ensure text has a very high color contrast.', 'technical': 'Ensure text meets a 7:1 contrast ratio (4.5:1 for large text).', 'impact': 'Users with more significant low vision.'},
    '1.4.7_low-or-no-background-audio': {'description': 'Ensure foreground speech is clearly distinguishable from background sound.', 'technical': 'Background audio should be at least 20 decibels lower than speech, or provide an option to turn it off.', 'impact': 'Users who are hard of hearing.'},
    '1.4.8_visual-presentation': {'description': 'Provide mechanisms to control the visual presentation of blocks of text.', 'technical': 'Allow users to select foreground/background colors, set line width, adjust spacing, and resize text to 200% without horizontal scrolling.', 'impact': 'Users with low vision and cognitive disabilities like dyslexia.'},
    '1.4.9_images-of-text-no-exception': {'description': 'Images of text are only used for pure decoration or when essential (like a logo).', 'technical': 'Strictly avoid using images of text for any informational content.', 'impact': 'Improves accessibility for all users who need to customize text presentation.'},
    '1.4.10_reflow': {'description': 'Content can be presented without loss of information or functionality, and without requiring two-dimensional scrolling.', 'technical': 'Ensure the page reflows into a single column when zoomed to 400%. Avoid content that requires both vertical and horizontal scrolling.', 'impact': 'Users with low vision who use screen magnification.'},
    '1.4.11_non-text-contrast': {'description': 'Ensure UI components and graphical objects have sufficient contrast.', 'technical': 'Ensure borders, icons, and state indicators (like a focus outline) have a 3:1 contrast ratio against adjacent colors.', 'impact': 'Users with low vision and color vision deficiencies.'},
    '1.4.12_text-spacing': {'description': 'Ensure no loss of content occurs when users adjust text spacing.', 'technical': 'Build components using relative units and flexible containers so that content does not get cut off or overlap when user-defined styles are applied.', 'impact': 'Users with low vision and dyslexia who use custom stylesheets to improve readability.'},
    '1.4.13_content-on-hover-or-focus': {'description': 'Ensure additional content shown on hover or focus is dismissible, hoverable, and persistent.', 'technical': 'Tooltips/popovers must not disappear when the user moves their mouse over them, and must be dismissible with the Esc key.', 'impact': 'Users with low vision who use magnification and might need to move their mouse to the tooltip to read it.'},
    # Operable
    '2.1.1_keyboard': {'description': 'All functionality is available from a keyboard.', 'technical': 'Ensure all interactive elements (links, buttons, form fields, custom widgets) can be reached and activated using the Tab, Shift+Tab, and Enter/Space keys.', 'impact': 'Users with motor disabilities who cannot use a mouse, and screen reader users.'},
    '2.1.2_no-keyboard-trap': {'description': 'Users can navigate away from any component using only the keyboard.', 'technical': 'If a component (like a modal dialog) traps focus, provide a clear and standard way to exit (e.g., the Esc key or a close button).', 'impact': 'Keyboard-only users who would otherwise get stuck and be unable to use the rest of the page.'},
    '2.1.3_keyboard-no-exception': {'description': 'All functionality is available from a keyboard without requiring specific timings for individual keystrokes.', 'technical': 'Avoid functionality that requires a key to be held down or pressed in a rapid sequence.', 'impact': 'Users with motor disabilities.'},
    '2.1.4_character-key-shortcuts': {'description': 'Allow users to turn off or reconfigure single-character key shortcuts.', 'technical': 'If using shortcuts like \'s\' for search, provide a setting to disable them or require a modifier key (e.g., Ctrl+S).', 'impact': 'Users of speech recognition software who may accidentally trigger shortcuts by speaking words.'},
    '2.2.1_timing-adjustable': {'description': 'Provide users with enough time to read and use content.', 'technical': 'For any time limits (e.g., session timeouts), provide an option to turn off, adjust, or extend the limit.', 'impact': 'Users with cognitive, motor, or reading disabilities who may need more time to complete tasks.'},
    '2.2.2_pause-stop-hide': {'description': 'Provide controls for moving, blinking, scrolling, or auto-updating information.', 'technical': 'For carousels, animations, or tickers, provide a clear pause/stop button.', 'impact': 'Users with attention disorders or vestibular disorders who can be distracted or made ill by moving content.'},
    '2.2.3_no-timing': {'description': 'Timing is not an essential part of the event or activity presented by the content.', 'technical': 'Avoid making tasks time-dependent unless it is for a real-time event (like an auction).', 'impact': 'All users with disabilities who may need more time.'},
    '2.2.4_interruptions': {'description': 'Interruptions can be postponed or suppressed by the user.', 'technical': 'Avoid pop-ups or updates that interrupt the user\'s workflow, unless they are essential (e.g., an emergency alert).', 'impact': 'Users with cognitive disabilities and screen reader users who can lose their place.'},
    '2.2.5_re-authenticating': {'description': 'Users can continue an activity after re-authenticating without loss of data.', 'technical': 'If a session expires, save the user\'s data (e.g., form entries) so it can be restored after they log back in.', 'impact': 'Users who take longer to complete tasks and may have their session time out.'},
    '2.2.6_timeouts': {'description': 'Warn users of the duration of inactivity that could cause data loss.', 'technical': 'If data is not preserved for more than 20 hours, inform the user about the inactivity timeout.', 'impact': 'Users who may be unaware that their work will be lost after a period of inactivity.'},
    '2.3.1_three-flashes-or-below-threshold': {'description': 'Content does not contain anything that flashes more than three times in any one-second period.', 'technical': 'Analyze videos and animations to ensure they do not contain rapid, large flashes that could trigger seizures.', 'impact': 'Users with photosensitive epilepsy.'},
    '2.3.2_three-flashes': {'description': 'Web pages do not contain anything that flashes more than three times in any one second period.', 'technical': 'A stricter version of 2.3.1, removing the "below threshold" exception.', 'impact': 'Users with photosensitive epilepsy.'},
    '2.3.3_animation-from-interactions': {'description': 'Motion animation triggered by interaction can be disabled.', 'technical': 'Use the `prefers-reduced-motion` CSS media query to disable or reduce non-essential animations for users who have requested it.', 'impact': 'Users with vestibular disorders who can be made ill by parallax scrolling or other motion effects.'},
    '2.4.1_bypass-blocks': {'description': 'Provide a mechanism to bypass blocks of content that are repeated on multiple pages.', 'technical': 'Implement a "Skip to main content" link at the beginning of the page, or use ARIA landmark roles.', 'impact': 'Keyboard-only and screen reader users who can avoid tabbing through navigation on every page.'},
    '2.4.2_page-titled': {'description': 'Provide web pages with titles that describe topic or purpose.', 'technical': 'Use a unique and descriptive `<title>` element for each page.', 'impact': 'All users, especially screen reader users who rely on the title to identify the page.'},
    '2.4.3_focus-order': {'description': 'The navigation order of focusable components is logical and predictable.', 'technical': 'Ensure the DOM order matches the visual order. Avoid using `tabindex` with a positive value, as it disrupts the natural order.', 'impact': 'Keyboard-only users who would be confused by a focus indicator jumping erratically around the page.'},
    '2.4.4_link-purpose-in-context': {'description': 'The purpose of each link can be determined from the link text alone or from its context.', 'technical': 'Use descriptive link text (e.g., "Read our Q3 financial report") instead of generic text ("Click here").', 'impact': 'Screen reader users who often navigate by listing all the links on a page.'},
    '2.4.5_multiple-ways': {'description': 'Provide more than one way to locate a web page within a set of pages.', 'technical': 'Provide a site map, a search function, and/or a clear navigation menu.', 'impact': 'All users, but especially those with cognitive or orientation difficulties.'},
    '2.4.6_headings-and-labels': {'description': 'Headings and labels describe the topic or purpose of the content they introduce.', 'technical': 'Write clear and descriptive text for headings (`<h1>`-`<h6>`) and form labels (`<label>`).', 'impact': 'Screen reader users who use headings to skim content, and all users who benefit from clear organization.'},
    '2.4.7_focus-visible': {'description': 'Ensure a keyboard focus indicator is always visible.', 'technical': 'Do not remove the default focus outline (e.g., `outline: none;`). If you customize it, ensure the custom indicator is highly visible.', 'impact': 'Sighted keyboard-only users who need to see where they are on the page.'},
    '2.4.8_location': {'description': 'Provide information about the user\'s location within a set of web pages.', 'technical': 'Use breadcrumbs, a site map, or clear headings to indicate the user\'s current position in the site hierarchy.', 'impact': 'Users with cognitive disabilities who can get lost on large websites.'},
    '2.4.9_link-purpose-link-only': {'description': 'The purpose of each link can be determined from the link text alone.', 'technical': 'A stricter version of 2.4.4. All links must be fully descriptive without needing surrounding context.', 'impact': 'Screen reader users.'},
    '2.4.10_section-headings': {'description': 'Use section headings to organize the content.', 'technical': 'Break up long-form content with a clear and logical hierarchy of `<h1>`-`<h6>` headings.', 'impact': 'Users with cognitive and learning disabilities, and screen reader users who navigate by headings.'},
    '2.4.11_focus-not-obscured-minimum': {'description': 'Ensure that when an element receives focus, it is not entirely hidden by other content.', 'technical': 'Make sure sticky headers/footers or other author-created content do not completely cover the focused element.', 'impact': 'Sighted keyboard-only users.'},
    '2.4.12_focus-not-obscured-enhanced': {'description': 'Ensure no part of a focused component is hidden by author-created content.', 'technical': 'A stricter version of 2.4.11, ensuring the entire component is visible.', 'impact': 'Sighted keyboard-only users.'},
    '2.4.13_focus-appearance': {'description': 'The focus indicator must have sufficient size and contrast.', 'technical': 'The focus indicator must be at least 2 CSS pixels thick and have a 3:1 contrast ratio against the unfocused state.', 'impact': 'Users with low vision who may not see a faint focus indicator.'},
    '2.5.1_pointer-gestures': {'description': 'All functionality that uses multipoint or path-based gestures can be operated with a single pointer.', 'technical': 'If a map uses pinch-to-zoom, also provide `+` and `-` buttons. If content uses a swipe gesture, provide next/previous buttons.', 'impact': 'Users with motor disabilities who can only use a standard pointer device and cannot perform complex gestures.'},
    '2.5.2_pointer-cancellation': {'description': 'Functionality can be cancelled or reversed.', 'technical': 'Trigger actions on the "up-event" (e.g., `mouseup` or `click`) rather than the "down-event" (`mousedown`). This allows users to move their finger/cursor away to cancel.', 'impact': 'Users with motor disabilities who may accidentally touch the screen or press a mouse button.'},
    '2.5.3_label-in-name': {'description': 'For components with a visible text label, the accessible name must contain the visible text.', 'technical': 'If a button says "Read More", its `aria-label` must be "Read More about Our Services", not just "Our Services".', 'impact': 'Users of speech recognition software who speak the visible label to activate a control.'},
    '2.5.4_motion-actuation': {'description': 'Functionality operated by device motion can also be operated by UI components.', 'technical': 'If an action can be triggered by shaking the device, also provide a button to trigger that action.', 'impact': 'Users with motor disabilities who cannot perform the required motion.'},
    '2.5.5_target-size-enhanced': {'description': 'The size of the target for pointer inputs is at least 44 by 44 CSS pixels.', 'technical': 'Ensure all clickable targets (buttons, links) are sufficiently large.', 'impact': 'Users with motor impairments, users with large fingers on touch screens, and users in unstable environments (e.g., a bus).'},
    '2.5.6_concurrent-input-mechanisms': {'description': 'Do not restrict the use of available input modalities (e.g., touch, keyboard, mouse).', 'technical': 'Design interfaces that can be used with a mouse, keyboard, and touch simultaneously without switching modes.', 'impact': 'Users who use multiple input methods, such as a keyboard and a touch screen.'},
    '2.5.7_dragging-movements': {'description': 'Provide a single pointer alternative for any functionality that uses a dragging movement.', 'technical': 'For a drag-and-drop interface, provide an alternative mechanism, such as selecting an item and then selecting a destination.', 'impact': 'Users with motor disabilities who find clicking-and-holding difficult.'},
    '2.5.8_target-size-minimum': {'description': 'The size of the target for pointer inputs is at least 24 by 24 CSS pixels.', 'technical': 'Ensure all clickable targets meet the minimum size, or have sufficient spacing from other targets.', 'impact': 'Users with motor impairments and touch screen users.'},
    # Understandable
    '3.1.1_language-of-page': {'description': 'Specify the default human language of the page.', 'technical': 'Add the `lang` attribute to the `<html>` element, e.g., `<html lang="en">`.', 'impact': 'Screen readers that use the attribute to switch to the correct voice profile for pronunciation.'},
    '3.1.2_language-of-parts': {'description': 'Specify the human language of specific passages or phrases in the content.', 'technical': 'Use the `lang` attribute on elements containing text in a different language, e.g., `<span lang="fr">C\'est la vie</span>`.', 'impact': 'Screen reader users, ensuring correct pronunciation of foreign words.'},
    '3.1.3_unusual-words': {'description': 'Provide a mechanism to identify specific definitions of unusual words or jargon.', 'technical': 'Provide a glossary, or use the `<dfn>` or `<abbr>` tags to define terms in-context.', 'impact': 'Users with cognitive disabilities, and users unfamiliar with the subject matter.'},
    '3.1.4_abbreviations': {'description': 'Provide a mechanism for identifying the expanded form of abbreviations.', 'technical': 'Use the `<abbr>` tag with a `title` attribute to provide the full text, e.g., `<abbr title="World Wide Web Consortium">W3C</abbr>`.', 'impact': 'All users who may not know the meaning of an abbreviation.'},
    '3.1.5_reading-level': {'description': 'When content requires advanced reading ability, provide a simpler alternative.', 'technical': 'Provide a simplified summary or an alternate version of the content written in plain language.', 'impact': 'Users with reading or cognitive disabilities.'},
    '3.1.6_pronunciation': {'description': 'Provide the specific pronunciation of words where meaning is ambiguous without it.', 'technical': 'Provide phonetic pronunciation in text or an audio clip, especially for words that are spelled the same but pronounced differently (homographs).', 'impact': 'Screen reader users and people with reading disabilities.'},
    '3.2.1_on-focus': {'description': 'Setting focus on a component does not cause a change of context.', 'technical': 'Do not trigger actions (like submitting a form or opening a new window) simply because an element receives focus. The user must explicitly activate it.', 'impact': 'Keyboard and screen reader users who would be disoriented by unexpected changes.'},
    '3.2.2_on-input': {'description': 'Changing the setting of a UI component does not automatically cause a change of context.', 'technical': 'Do not automatically submit a form or navigate to a new page when a user makes a selection in a dropdown list. Provide a separate "Submit" button.', 'impact': 'Users who may not be ready for a change to occur and could be disoriented.'},
    '3.2.3_consistent-navigation': {'description': 'Navigational mechanisms that are repeated on multiple pages appear in the same relative order.', 'technical': 'Keep the main navigation, header, and footer consistent across all pages of a site.', 'impact': 'Users with cognitive disabilities, low vision, and screen reader users who rely on predictability.'},
    '3.2.4_consistent-identification': {'description': 'Components with the same functionality are identified consistently.', 'technical': 'Use the same icon and label for a function across all pages. E.g., a shopping cart icon should always look the same and have the same accessible name.', 'impact': 'All users, especially those with cognitive disabilities, who benefit from consistency.'},
    '3.2.5_change-on-request': {'description': 'Changes of context are initiated only by user request, or a mechanism is available to turn them off.', 'technical': 'Avoid auto-redirects, carousels that auto-advance, or other automatic content updates. If they exist, provide a control to stop them.', 'impact': 'Screen reader users and users with cognitive disabilities who can be disoriented by unexpected changes.'},
    '3.2.6_consistent-help': {'description': 'If a help mechanism is provided, it is located consistently across pages.', 'technical': 'Place the link to a "Help" or "Contact Us" page in the same location (e.g., the footer) on every page.', 'impact': 'Users who need assistance and benefit from a predictable way to find it.'},
    '3.3.1_error-identification': {'description': 'If an input error is automatically detected, the item in error is identified and the error is described in text.', 'technical': 'Clearly highlight the field with the error and provide a text message explaining what is wrong. Use `aria-describedby` to link the error message to the input.', 'impact': 'All users, but especially screen reader users who need the error to be announced.'},
    '3.3.2_labels-or-instructions': {'description': 'Provide labels or instructions when content requires user input.', 'technical': 'Use the `<label>` element for all form controls. Provide clear instructions for required formats (e.g., "Date (MM/DD/YYYY)").', 'impact': 'All users, especially screen reader users who need the label to understand the purpose of a form field.'},
    '3.3.3_error-suggestion': {'description': 'If an input error is known, suggestions for correction are provided.', 'technical': 'If a username is taken, suggest alternatives. If a date is in the wrong format, state the correct format.', 'impact': 'Users with cognitive or learning disabilities who may have trouble correcting errors.'},
    '3.3.4_error-prevention-legal-financial-data': {'description': 'For pages that cause legal commitments or financial transactions, submissions are reversible, checked, or confirmed.', 'technical': 'Provide a confirmation page before finalizing a purchase, or allow users to cancel an order within a certain timeframe.', 'impact': 'Users with disabilities who are more prone to making mistakes.'},
    '3.3.5_help': {'description': 'Provide context-sensitive help.', 'technical': 'Provide instructions and guidance in-context, for example, a tooltip explaining a complex field, or a link to a help page.', 'impact': 'Users with cognitive and learning disabilities.'},
    '3.3.6_error-prevention-all': {'description': 'For all pages that require user submission, the submission is reversible, checked, or confirmed.', 'technical': 'A stricter version of 3.3.4, applying the same logic to all forms, not just legal/financial ones.', 'impact': 'All users who could make a mistake.'},
    '3.3.7_redundant-entry': {'description': 'Avoid requiring the user to re-enter information they have already provided in the same session.', 'technical': 'Auto-populate fields where possible. For example, if the shipping and billing addresses are the same, provide a checkbox to copy the information.', 'impact': 'Users with cognitive and motor disabilities who may find re-typing information difficult or error-prone.'},
    '3.3.8_accessible-authentication-minimum': {'description': 'Do not require a cognitive function test unless it is to recognize objects or personal content.', 'technical': 'Avoid puzzles, transcription, or memory tasks for authentication. Allow use of password managers (copy/paste is enabled).', 'impact': 'Users with cognitive disabilities, such as memory loss or dyslexia.'},
    '3.3.9_accessible-authentication-enhanced': {'description': 'Do not require a cognitive function test as part of an authentication process.', 'technical': 'A stricter version of 3.3.8. A cognitive test cannot be the only method of authentication; an alternative must be provided.', 'impact': 'Users with cognitive disabilities.'},
    # Robust
    '4.1.1_parsing': {'description': 'This criterion is obsolete and removed in WCAG 2.2.', 'technical': 'Formerly required valid, well-formed HTML. Its goals are now better covered by 4.1.2 and modern browser tolerance. Focus on writing valid code and correct ARIA usage.', 'impact': 'N/A as it is removed. The underlying principle helps assistive technology interpret content reliably.'},
    '4.1.2_name-role-value': {'description': 'Ensure all UI components have a name and role, and that their state can be programmatically determined.', 'technical': 'Use native HTML elements correctly or add appropriate ARIA roles, states, and properties (e.g., `role="button"`, `aria-pressed="true"`) to custom components.', 'impact': 'Screen reader users whose software relies on this information to convey the purpose and state of controls.'},
    '4.1.3_status-messages': {'description': 'Status messages can be programmatically determined so they can be presented to the user without receiving focus.', 'technical': 'Use an ARIA live region (`role="status"`, `role="alert"`, or `aria-live`) to wrap content that updates dynamically (e.g., "Item added to cart", "Search results updated").', 'impact': 'Screen reader users who need to be notified of important changes on the page without losing their current focus.'},
}

PAGE_TYPE_PATTERNS = {
    'homepage': [r'/$', r'/index\.html$', r'/home$'],
    'search': [r'/search', r'/cerca', r'/find'],
    'product': [r'/product', r'/prodotto', r'/item'],
    'category': [r'/category', r'/categoria', r'/department'],
    'cart': [r'/cart', r'/carrello', r'/basket'],
    'checkout': [r'/checkout', r'/acquista', r'/payment'],
    'login': [r'/login', r'/accedi', r'/signin'],
    'register': [r'/register', r'/registrazione', r'/signup'],
    'account': [r'/account', r'/profilo', r'/user'],
    'contact': [r'/contact', r'/contatti', r'/support'],
    'article': [r'/article', r'/articolo', r'/post', r'/blog'],
    'about': [r'/about', r'/chi-siamo', r'/azienda'],
}

# Consolidated Funnel Configuration
# Combines previous funnel_categories and funnel_metadata
FUNNEL_CONFIG = {
    'checkout': {
        'description': 'Purchase completion flow',
        'steps': ['cart', 'checkout', 'payment', 'confirmation'], # Order matters
        'critical_steps': ['payment', 'confirmation'], # Steps crucial for completion
        'severity_multiplier': 2.0, # Higher weight for issues in this funnel
        'step_patterns': { # Regex patterns to identify steps by URL path
             'cart': [r'/cart', r'/basket', r'/bag'],
             'checkout': [r'/checkout', r'/order', r'/shipping', r'/address'],
             'payment': [r'/payment', r'/pay', r'/billing'],
             'confirmation': [r'/confirm', r'/success', r'/thank-you', r'/ordine-confermato'],
         }
    },
    'registration': {
        'description': 'New user registration flow',
        'steps': ['register', 'verification', 'profile'],
        'critical_steps': ['verification'],
        'severity_multiplier': 1.5,
        'step_patterns': {
             'register': [r'/register', r'/sign-up', r'/create-account', r'/registrazione'],
             'verification': [r'/verify', r'/confirmation', r'/activate', r'/verifica'],
             'profile': [r'/profile', r'/account/setup', r'/preferences', r'/profilo'],
         }
    },
    'login': {
        'description': 'User authentication flow',
        'steps': ['login', 'account', 'dashboard'],
        'critical_steps': ['login'],
        'severity_multiplier': 1.5,
         'step_patterns': {
             'login': [r'/login', r'/sign-in', r'/auth', r'/accedi'],
             'account': [r'/account', r'/profile', r'/my-account', r'/area-personale'],
             'dashboard': [r'/dashboard', r'/overview', r'/home'], # Might overlap with homepage
         }
    },
    'search': {
        'description': 'Product search and discovery flow',
        'steps': ['search', 'results', 'filters', 'product'],
        'critical_steps': ['results', 'product'],
        'severity_multiplier': 1.2,
        'step_patterns': {
            'search': [r'/search', r'/find', r'/cerca'],
            'results': [r'/results', r'/search-results', r'/products', r'/prodotti'],
            'filters': [r'/filter', r'/refine', r'/sort', r'/filtri'],
            'product': [r'/product/', r'/item/', r'/detail/', r'/prodotto/'] # Note trailing slash for specificity
         }
    }
    # Add other funnels as needed
}

# Initialize configuration manager (global for simplicity or pass instance)
config_manager = ConfigurationManager(project_name="axeScraper")

class AccessibilityAnalyzer:
    """
    Optimized: Accessibility analysis tool that processes data from axe DevTools
    and Crawler, generating accurate metrics and reports with clear visualizations.
    Handles optional crawler data (.pkl) and prioritizes '_concat' input files.
    """

    def __init__(self, log_level=None, max_workers=None, output_manager=None):
        """Initialize the analyzer with logging configuration and parallelism options."""
        self.output_manager = output_manager
        self.logger = get_logger(
            "report_analysis",
            config_manager.get_logging_config()["components"]["report_analysis"],
            output_manager=self.output_manager
        )

        if output_manager:
            self.domain_slug = output_manager.domain_slug
        else:
            # Attempt to derive from input file name if needed, or default
            self.domain_slug = "unknown_domain" # Consider improving this later

        self.max_workers = max_workers or config_manager.get_int("REPORT_ANALYSIS_MAX_WORKERS", 4)

        # Use configurations defined outside __init__
        self.impact_weights = IMPACT_WEIGHTS
        self.wcag_categories = WCAG_CATEGORIES
        self.solution_mapping = SOLUTION_MAPPING
        self.page_type_patterns = PAGE_TYPE_PATTERNS
        self.funnel_config = FUNNEL_CONFIG

        # Caches
        self._url_type_cache = {}
        self._normalized_url_cache = {}
        self._wcag_mapping_cache = {}
        self._funnel_step_cache = {} # Cache for funnel step identification

    def normalize_url(self, url: str) -> str:
        """
        Normalize URL (lowercase scheme/netloc) using cache.
        Crucially, PRESERVES the fragment identifier (#...) as it's used for routing in SPAs.
        Optionally removes trailing slash from path *only if* there is no fragment.

        Args:
            url: URL to normalize

        Returns:
            Normalized URL or empty string if input is invalid.
        """
        if not url or not isinstance(url, str):
            self.logger.debug("normalize_url received invalid input.")
            return ""
        # Check cache first
        if url in self._normalized_url_cache:
            return self._normalized_url_cache[url]

        try:
            parsed = urlparse(url)
            scheme = parsed.scheme.lower() if parsed.scheme else 'http'
            netloc = parsed.netloc.lower()
            path = parsed.path
            query = parsed.query
            fragment = parsed.fragment # Keep the original fragment

            # Basic check: if fragment is just '#', treat it as empty
            if fragment == '#':
                fragment = ''

            # Reconstruct URL using urlunparse, explicitly including the fragment
            normalized_url = urlunparse((
                scheme,
                netloc,
                path,
                '', # params - usually empty
                query,
                fragment # <-- Keep the fragment
            ))

            # Optional: remove trailing slash from path *only if* there's no fragment
            # And if the path itself is not just "/"
            if not fragment and len(path) > 1 and path.endswith('/'):
                 # Rebuild without trailing slash if path had one and no fragment exists
                 normalized_url = urlunparse((scheme, netloc, path[:-1], '', query, ''))


            self._normalized_url_cache[url] = normalized_url
            # self.logger.debug(f"Normalized '{url}' to '{normalized_url}'") # Uncomment for debugging normalization
            return normalized_url
        except Exception as e:
            self.logger.warning(f"Could not normalize URL '{url}': {e}. Returning original.")
            # Cache original on error to avoid repeated attempts
            self._normalized_url_cache[url] = url
            return url
        
    def get_page_type(self, url: str) -> str:
        """
        Identify page type based on predefined patterns in the URL path.

        Args:
            url: Normalized URL to identify

        Returns:
            Identified page type or 'other'.
        """
        if url in self._url_type_cache:
            return self._url_type_cache[url]

        if not url:
            return 'other'

        try:
            path = urlparse(url).path
            if not path: # Handle cases where URL might just be domain
                 path = '/'
            # Ensure path ends consistently for pattern matching if needed
            # path = path if path.endswith('/') else path + '/' # Optional: Depends on patterns

        except Exception:
             path = '/' # Default path on parsing error


        for page_type, patterns in self.page_type_patterns.items():
            for pattern in patterns:
                # Match against the path part of the URL
                if re.search(pattern, path, re.IGNORECASE):
                    self._url_type_cache[url] = page_type
                    return page_type

        self._url_type_cache[url] = 'other'
        return 'other'

    def _identify_funnel_step(self, normalized_url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Identifies the funnel name and step for a given normalized URL based on FUNNEL_CONFIG.

        Args:
            normalized_url: The normalized URL to check.

        Returns:
            Tuple (funnel_name, funnel_step) or (None, None) if not found.
        """
        if normalized_url in self._funnel_step_cache:
            return self._funnel_step_cache[normalized_url]

        try:
             path = urlparse(normalized_url).path
             if not path: path = '/' # Handle root path
        except Exception:
             path = '/'

        for funnel_name, config in self.funnel_config.items():
            for step_name, patterns in config.get('step_patterns', {}).items():
                for pattern in patterns:
                     # Match against the path part of the URL
                    if re.search(pattern, path, re.IGNORECASE):
                        result = (funnel_name, step_name)
                        self._funnel_step_cache[normalized_url] = result
                        return result

        # If no match found
        self._funnel_step_cache[normalized_url] = (None, None)
        return None, None


    def load_data(self, input_excel: Optional[str] = None, crawler_state: Optional[str] = None) -> pd.DataFrame:
        """Load data from an Excel file and optionally integrate crawler data."""
        # Use output manager to get default paths if not provided
        if self.output_manager:
            if input_excel is None:
                 # Prioritize _concat file based on user feedback
                concat_path = self.output_manager.get_path(
                    "axe", f"accessibility_report_{self.output_manager.domain_slug}_concat.xlsx")
                default_path = self.output_manager.get_path(
                     "axe", f"accessibility_report_{self.output_manager.domain_slug}.xlsx")

                if concat_path.exists():
                     input_excel = str(concat_path)
                     self.logger.info(f"Using default input file: {input_excel} (found _concat version)")
                elif default_path.exists():
                    input_excel = str(default_path)
                    self.logger.info(f"Using default input file: {input_excel} (standard version)")
                else:
                     # Let it fail later if neither exists and no input was given
                     input_excel = str(concat_path) # Point to expected concat path for error message
                     self.logger.warning(f"Default input Excel file not found: {concat_path} or {default_path}")


            if crawler_state is None:
                crawler_state_path = self.output_manager.get_path(
                    "crawler", f"crawler_state_{self.output_manager.domain_slug}.pkl")
                if crawler_state_path.exists():
                    crawler_state = str(crawler_state_path)
                else:
                     # It's optional, so just log if not found by default
                     self.logger.info(f"Optional crawler state file not found at default path: {crawler_state_path}")
                     crawler_state = None # Ensure it's None if not found

        if not input_excel:
             raise ValueError("Input Excel file path must be provided either via argument or found by OutputManager.")

        self.logger.info(f"Loading data from: {input_excel}")
        input_path = Path(input_excel)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_excel}")

        try:
            # Specify sheet_name=None to load all sheets, or 0 for the first sheet
            # If _concat files always have data in the first sheet, use sheet_name=0
            df = pd.read_excel(input_excel, sheet_name=0) # Assuming data is in the first sheet for _concat
            self.logger.info(f"Loaded Excel with {len(df)} rows from the first sheet.")
        except Exception as e:
             self.logger.error(f"Failed to load Excel file {input_excel}: {e}")
             raise

        required_columns = ['violation_id', 'impact', 'page_url'] # Add other essential columns if needed
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns in {input_excel}: {', '.join(missing_columns)}")

        # Initial cleaning and processing
        df = self._clean_data(df)

        # Integrate crawler data if path is valid
        if crawler_state:
            df = self._integrate_crawler_data(df, crawler_state)
        else:
             # Ensure 'template' column exists even if crawler data is not used
             if 'template' not in df.columns:
                  df['template'] = 'Unknown'
             self.logger.info("Skipping crawler data integration (no file specified or found). Template analysis will be limited.")

        return df

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean, normalize, and enrich the DataFrame with page type, WCAG info,
        and funnel identification.
        """
        self.logger.info("Cleaning and enriching data...")
        clean_df = df.copy()
        original_count = len(clean_df)

        # --- Basic Cleaning ---
        essential_cols = ['violation_id', 'impact', 'page_url']
        clean_df = clean_df.dropna(subset=essential_cols)
        if len(clean_df) < original_count:
             self.logger.info(f"Dropped {original_count - len(clean_df)} rows with missing essential data.")

        # --- URL Normalization and Page Type Identification ---
        self.logger.info("Normalizing URLs and identifying page types...")
        # Use ThreadPoolExecutor for potentially faster processing on large datasets
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            normalized_urls = list(executor.map(self.normalize_url, clean_df['page_url']))
        clean_df['normalized_url'] = normalized_urls

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
             page_types = list(executor.map(self.get_page_type, clean_df['normalized_url']))
        clean_df['page_type'] = page_types

        # --- Impact Processing ---
        self.logger.info("Processing impact levels...")
        clean_df['impact'] = clean_df['impact'].astype(str).str.lower().str.strip()
        valid_impacts = list(self.impact_weights.keys())
        # Map invalid impacts to 'unknown'
        clean_df.loc[~clean_df['impact'].isin(valid_impacts), 'impact'] = 'unknown'
        clean_df['severity_score'] = clean_df['impact'].map(self.impact_weights)

        # --- Log URL Normalizzati PRIMA della deduplicazione ---
        self.logger.debug(f"[_clean_data] PRIMA drop_duplicates - URL Normalizzati unici: {clean_df['normalized_url'].nunique()}")
        self.logger.debug(f"[_clean_data] PRIMA drop_duplicates - Valori URL Normalizzati (Top 20):\n{clean_df['normalized_url'].value_counts().head(20).to_string()}")

        # --- Deduplication ---
        self.logger.info("Removing duplicate violation instances...") # Log aggiunto per chiarezza
        initial_rows_before_dedup = len(clean_df) # Salva il numero di righe prima
        dedup_cols = ['normalized_url', 'violation_id']
        if 'html_element' in clean_df.columns:
            dedup_cols.append('html_element')
            self.logger.debug(f"[_clean_data] Using drop_duplicates columns: {dedup_cols}")
        else:
            self.logger.debug(f"[_clean_data] Using drop_duplicates columns: {dedup_cols} ('html_element' not found)")

        clean_df = clean_df.drop_duplicates(subset=dedup_cols, keep='first')
        rows_removed = initial_rows_before_dedup - len(clean_df) # Calcola righe rimosse
        if rows_removed > 0:
            # Modifica il log esistente per essere più informativo
            self.logger.info(f"Removed {rows_removed} duplicate violation instances (based on {', '.join(dedup_cols)}).")
        else:
            self.logger.info("No duplicate violation instances removed.")

        # --- Log URL Normalizzati DOPO la deduplicazione ---
        self.logger.debug(f"[_clean_data] DOPO drop_duplicates - URL Normalizzati unici: {clean_df['normalized_url'].nunique()}")
        self.logger.debug(f"[_clean_data] DOPO drop_duplicates - Valori URL Normalizzati (Top 20):\n{clean_df['normalized_url'].value_counts().head(20).to_string()}")


        # --- WCAG Information ---
        self.logger.info("Mapping violations to WCAG categories...")
        clean_df['wcag_category'] = clean_df['violation_id'].apply(self._get_wcag_category)
        clean_df['wcag_criterion'] = clean_df['violation_id'].apply(self._get_wcag_criterion)
        clean_df['wcag_name'] = clean_df['violation_id'].apply(self._get_wcag_name)

        # --- Funnel Identification and Scoring ---
        self.logger.info("Identifying funnel steps and calculating funnel scores...")
        funnel_info = clean_df['normalized_url'].apply(self._identify_funnel_step)
        clean_df['funnel_name'] = funnel_info.apply(lambda x: x[0] if x[0] else 'none')
        clean_df['funnel_step'] = funnel_info.apply(lambda x: x[1] if x[1] else 'none')
        clean_df['is_in_funnel'] = clean_df['funnel_name'] != 'none'

        # Calculate funnel-specific severity score using dynamic multiplier from config
        def calculate_funnel_score(row):
            base_score = row['severity_score']
            if row['is_in_funnel']:
                funnel_name = row['funnel_name']
                multiplier = self.funnel_config.get(funnel_name, {}).get('severity_multiplier', 1.0) # Default multiplier 1 if funnel not in config
                return base_score * multiplier
            return base_score

        clean_df['funnel_severity_score'] = clean_df.apply(calculate_funnel_score, axis=1)

        # --- Final Touches ---
        clean_df['analysis_date'] = datetime.now().strftime("%Y-%m-%d")

        self.logger.info(f"Data cleaning complete. Original rows: {original_count}, Final rows: {len(clean_df)}")

        # Log funnel data statistics if present
        funnel_violations = clean_df['is_in_funnel'].sum()
        if funnel_violations > 0:
            total_rows = len(clean_df)
            funnel_pct = (funnel_violations / total_rows) * 100 if total_rows > 0 else 0
            self.logger.info(f"Identified {funnel_violations} funnel-related violations ({funnel_pct:.1f}% of total)")
            funnel_counts = clean_df[clean_df['is_in_funnel']].groupby('funnel_name').size()
            for name, count in funnel_counts.items():
                self.logger.info(f"  - Funnel '{name}': {count} violations")
            step_counts = clean_df[clean_df['is_in_funnel']].groupby(['funnel_name', 'funnel_step']).size()
            self.logger.info(f"Funnel step distribution:\n{step_counts.to_string()}")
        else:
             self.logger.info("No funnel-related violations identified based on URL patterns.")

        return clean_df

    def _get_wcag_mapping(self, violation_id: str, field: str) -> str:
        """Helper to get WCAG info with caching."""
        cache_key = (violation_id, field)
        if cache_key in self._wcag_mapping_cache:
            return self._wcag_mapping_cache[cache_key]

        # Use lowercase violation_id for matching
        violation_id_lower = violation_id.lower()
        # Find best match (prioritize longer keys if using 'in')
        # Simple 'in' match for now, with comment about potential inaccuracy
        matching_key = None
        best_match_len = 0
        for key in self.wcag_categories:
             # Check if the key exists in the violation id
            if key in violation_id_lower:
                 # If this key is longer than the previous best match, update
                 if len(key) > best_match_len:
                    best_match_len = len(key)
                    matching_key = key

        if matching_key:
             result = self.wcag_categories[matching_key].get(field, "Other" if field == 'category' else "N/A")
        else:
             result = "Other" if field == 'category' else "N/A"

        self._wcag_mapping_cache[cache_key] = result
        return result

    def _get_wcag_category(self, violation_id: str) -> str:
        """Get WCAG category for a violation ID."""
        return self._get_wcag_mapping(violation_id, 'category')

    def _get_wcag_criterion(self, violation_id: str) -> str:
        """Get WCAG criterion for a violation ID."""
        return self._get_wcag_mapping(violation_id, 'criterion')

    def _get_wcag_name(self, violation_id: str) -> str:
        """Get WCAG name for a violation ID."""
        return self._get_wcag_mapping(violation_id, 'name')


    def _integrate_crawler_data(self, df: pd.DataFrame, crawler_state_path: str) -> pd.DataFrame:
        """
        Integrate crawler data (templates, depth) if the state file exists and is valid.
        Handles different state file formats and ensures 'template' column exists.
        """
        self.logger.info(f"Attempting to integrate crawler data from: {crawler_state_path}")
        state_file = Path(crawler_state_path)

        if not state_file.exists():
            self.logger.warning(f"Crawler state file not found: {crawler_state_path}. Skipping integration.")
            if 'template' not in df.columns: df['template'] = 'Unknown'
            # Add other crawler-related columns with default values if needed
            # if 'page_depth' not in df.columns: df['page_depth'] = 0
            return df

        try:
            with open(state_file, 'rb') as f:
                state = pickle.load(f)
            self.logger.info("Crawler state file loaded successfully.")

            url_tree = {}
            structures = {} # This dictionary maps template hash/ID to its data

            # --- Detect state format ---
            # Option 1: New multi-domain format? (Check structure)
            if isinstance(state, dict) and "domain_data" in state and isinstance(state["domain_data"], dict):
                self.logger.info("Detected multi-domain crawler state format.")
                found_domain_data = False
                for domain_key, domain_data in state["domain_data"].items():
                     # Try to match based on domain_slug derived from output_manager
                    if isinstance(domain_data, dict) and self.domain_slug in domain_key.lower():
                        self.logger.info(f"Found matching domain data for key '{domain_key}'")
                        url_tree = domain_data.get("url_tree", {})
                        structures = domain_data.get("structures", {})
                        found_domain_data = True
                        break
                if not found_domain_data:
                     self.logger.warning(f"Could not find data for domain slug '{self.domain_slug}' in multi-domain state file.")

            # Option 2: Older direct format?
            elif isinstance(state, dict) and ("url_tree" in state or "structures" in state):
                self.logger.info("Detected direct (single-domain or older) crawler state format.")
                url_tree = state.get("url_tree", {})
                structures = state.get("structures", {})

            # Option 3: Unknown format
            else:
                 self.logger.warning(f"Unrecognized crawler state format in {crawler_state_path}. Cannot extract templates.")
                 if 'template' not in df.columns: df['template'] = 'Unknown'
                 return df # Return df with default 'Unknown' template

            # --- Map URLs to Templates ---
            if not structures:
                 self.logger.warning("No 'structures' data found in the loaded crawler state.")
                 if 'template' not in df.columns: df['template'] = 'Unknown'
                 return df

            url_to_template = {}
            for template_id, template_data in structures.items():
                 # The template data should contain a list of URLs belonging to this template
                 # Common key names: 'urls', 'url_list'
                 urls_in_template = []
                 if isinstance(template_data, dict):
                     urls_in_template = template_data.get('urls', []) or template_data.get('url_list', [])
                     # Sometimes the representative URL might be under 'url' key
                     rep_url = template_data.get('url')
                     if rep_url and rep_url not in urls_in_template:
                          urls_in_template.append(rep_url)
                 elif isinstance(template_data, list): # Handle case where structure value is just a list of URLs
                      urls_in_template = template_data

                 if not urls_in_template:
                     #self.logger.debug(f"Template '{template_id}' has no associated URLs in state file.")
                     continue

                 for url in urls_in_template:
                      normalized_url = self.normalize_url(url)
                      if normalized_url:
                           url_to_template[normalized_url] = template_id # Map normalized URL to template ID

            self.logger.info(f"Mapped {len(url_to_template)} URLs to {len(structures)} templates from crawler state.")

            # --- Add 'template' column to DataFrame ---
            # Map using the normalized URL; default to 'Unknown' if no match
            df['template'] = df['normalized_url'].map(url_to_template).fillna('Unknown')

            unknown_template_count = (df['template'] == 'Unknown').sum()
            if unknown_template_count > 0:
                 self.logger.info(f"{unknown_template_count} rows could not be mapped to a known template.")

            # Placeholder for integrating page depth or other crawler data if needed
            # e.g., url_depth = {self.normalize_url(url): data['depth'] for url, data in url_tree.items() if 'depth' in data}
            # df['page_depth'] = df['normalized_url'].map(url_depth).fillna(0)

            self.logger.info("Successfully integrated template information from crawler data.")

        except FileNotFoundError:
             # This case is handled at the beginning, but kept for robustness
             self.logger.warning(f"Crawler state file not found: {crawler_state_path}.")
             if 'template' not in df.columns: df['template'] = 'Unknown'
        except pickle.UnpicklingError:
             self.logger.error(f"Error unpickling crawler state file: {crawler_state_path}. File might be corrupted.")
             if 'template' not in df.columns: df['template'] = 'Unknown'
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during crawler data integration: {e}", exc_info=True)
            if 'template' not in df.columns: df['template'] = 'Unknown' # Ensure column exists on error

        return df


    def _empty_metrics(self) -> Dict:
        """Return a dictionary with zeroed/default metrics for empty input."""
        return {
            'Total Violations': 0,
            'Unique Pages': 0,
            'Unique Violation Types': 0,
            'Critical Violations': 0,
            'Serious Violations': 0,
            'Moderate Violations': 0,
            'Minor Violations': 0,
            'Unknown Violations': 0,
            'Average Violations per Page': 0,
            'Weighted Severity Score': 0,
            'Pages with Critical Issues (%)': 0,
            'Page Type Analysis': {},
            'Top WCAG Issues': {},
            'WCAG Conformance Score': 0,
            'WCAG Conformance Level': 'N/A',
            'Funnel Analysis': {} # Keep funnel analysis section empty too
        }

    def calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """
        Calculate accessibility metrics including basic stats, impact distribution,
        page type analysis, WCAG conformance, and funnel analysis.

        Args:
            df: DataFrame with cleaned accessibility data.

        Returns:
            Dictionary of calculated metrics.
        """
        if df.empty:
            self.logger.warning("Input DataFrame is empty. Returning default metrics.")
            return self._empty_metrics()

        self.logger.info("Calculating accessibility metrics...")
        metrics = {}

        # --- Basic Metrics ---
        metrics['Total Violations'] = len(df)
        metrics['Unique Pages'] = df['normalized_url'].nunique()
        metrics['Unique Violation Types'] = df['violation_id'].nunique()

        # --- Impact Distribution ---
        impact_counts = df['impact'].value_counts().to_dict()
        # Ensure all impact levels are present, even if zero
        for impact_level in self.impact_weights.keys():
             metrics[f'{impact_level.capitalize()} Violations'] = impact_counts.get(impact_level, 0)

        # --- Per-Page & Severity Metrics ---
        unique_pages = metrics['Unique Pages']
        avg_per_page = metrics['Total Violations'] / unique_pages if unique_pages > 0 else 0
        metrics['Average Violations per Page'] = round(avg_per_page, 2)

        # Weighted score based on impact weights per page
        total_severity = df['severity_score'].sum()
        metrics['Weighted Severity Score'] = round(total_severity / unique_pages, 2) if unique_pages > 0 else 0

        # Trova tutte le pagine che hanno almeno UNA violazione critica
        pages_with_critical = set(df[df['impact'] == 'critical']['normalized_url'].unique())
        all_pages = set(df['normalized_url'].unique())
        num_critical_pages = len(pages_with_critical)
        num_total_pages = len(all_pages)
        critical_page_pct = (num_critical_pages / num_total_pages * 100) if num_total_pages > 0 else 0
        metrics['Pages with Critical Issues (%)'] = round(critical_page_pct, 2)
        self.logger.debug(f"Pages with critical: {num_critical_pages}, Total pages: {num_total_pages}, Percent: {critical_page_pct}")

        # --- Page Type Metrics ---
        metrics['Page Type Analysis'] = self._calculate_page_type_metrics(df)

        # --- WCAG Metrics ---
        metrics.update(self._calculate_wcag_metrics(df))

        # --- Conformance Metrics ---
        metrics.update(self._calculate_conformance_metrics(
            df, impact_counts, unique_pages, num_critical_pages))

        # --- Funnel Analysis Metrics ---
        # Perform funnel analysis only if funnel data exists ('is_in_funnel' column is True for some rows)
        if 'is_in_funnel' in df.columns and df['is_in_funnel'].any():
             funnel_df = df[df['is_in_funnel']].copy() # Work with a copy of the funnel data
             self.logger.info(f"Calculating metrics for {funnel_df['funnel_name'].nunique()} funnels...")

             funnel_analysis_metrics = {
                 'Total Funnels Identified': funnel_df['funnel_name'].nunique(),
                 'Total Pages in Funnels': funnel_df['normalized_url'].nunique(),
                 'Total Violations in Funnels': len(funnel_df),
             }

             # Avg violations per funnel page
             funnel_pages_count = funnel_analysis_metrics['Total Pages in Funnels']
             funnel_analysis_metrics['Average Violations per Funnel Page'] = round(
                 len(funnel_df) / funnel_pages_count, 2) if funnel_pages_count > 0 else 0

             # Funnel impact distribution
             funnel_impact_counts = funnel_df['impact'].value_counts().to_dict()
             for impact in self.impact_weights.keys():
                 funnel_analysis_metrics[f'{impact.capitalize()} Funnel Violations'] = funnel_impact_counts.get(impact, 0)

             # Per-funnel breakdown
             funnel_details = {}
             for funnel_name, group in funnel_df.groupby('funnel_name'):
                 pages_in_funnel = group['normalized_url'].nunique()
                 crit_pages_in_funnel = group[group['impact'] == 'critical']['normalized_url'].nunique()
                 crit_pct_in_funnel = (crit_pages_in_funnel / pages_in_funnel * 100) if pages_in_funnel > 0 else 0
                 # Use 'funnel_severity_score' for weighted score calculation
                 weighted_score = group['funnel_severity_score'].sum() / pages_in_funnel if pages_in_funnel > 0 else 0

                 funnel_details[funnel_name] = {
                     'Pages': pages_in_funnel,
                     'Total Violations': len(group),
                     'Avg Violations per Page': round(len(group) / pages_in_funnel, 2) if pages_in_funnel > 0 else 0,
                     'Critical Violations': group[group['impact'] == 'critical'].shape[0],
                     'Serious Violations': group[group['impact'] == 'serious'].shape[0], # Add serious count
                     'Critical Pages': crit_pages_in_funnel,
                     'Critical Pages (%)': round(crit_pct_in_funnel, 2),
                     'Weighted Score': round(weighted_score, 2) # Score reflecting funnel multiplier
                 }

             funnel_analysis_metrics['Funnel Details'] = funnel_details

             # Identify most problematic funnel based on Weighted Score
             if funnel_details:
                 sorted_funnels = sorted(funnel_details.items(), key=lambda item: item[1]['Weighted Score'], reverse=True)
                 funnel_analysis_metrics['Most Problematic Funnel'] = sorted_funnels[0][0]
                 funnel_analysis_metrics['Most Problematic Funnel Score'] = sorted_funnels[0][1]['Weighted Score']


             # Per-step breakdown (within funnels)
             step_metrics = {}
             for (funnel_name, step_name), group in funnel_df.groupby(['funnel_name', 'funnel_step']):
                 # Ignore 'none' step if it appears unexpectedly
                 if step_name == 'none': continue

                 step_key = f"{funnel_name}: {step_name}"
                 step_pages = group['normalized_url'].nunique()
                 step_metrics[step_key] = {
                     'Funnel': funnel_name,
                     'Step': step_name,
                     'Pages': step_pages,
                     'Violations': len(group),
                     'Critical': group[group['impact'] == 'critical'].shape[0],
                     'Serious': group[group['impact'] == 'serious'].shape[0],
                     'Weighted Score': round(group['funnel_severity_score'].sum() / step_pages, 2) if step_pages > 0 else 0,
                 }

             # Sort steps by Critical, then Serious, then Weighted Score
             if step_metrics:
                  sorted_steps = sorted(step_metrics.items(),
                                        key=lambda item: (item[1]['Critical'], item[1]['Serious'], item[1]['Weighted Score']),
                                        reverse=True)
                  # Store top N problematic steps (e.g., top 5)
                  funnel_analysis_metrics['Top Problematic Steps'] = dict(sorted_steps[:5])

             metrics['Funnel Analysis'] = funnel_analysis_metrics
        else:
             metrics['Funnel Analysis'] = {'Status': 'No funnel data identified or processed.'}
             self.logger.info("No funnel data found in DataFrame, skipping funnel metrics calculation.")

        self.logger.info("Metrics calculation completed.")
        # self.logger.debug(f"Calculated Metrics: {json.dumps(metrics, indent=2, default=str)}") # DEBUG: Log metrics if needed
        return metrics

    def _calculate_page_type_metrics(self, df: pd.DataFrame) -> Dict:
        """Calculate metrics grouped by page type."""
        self.logger.debug("Calculating page type metrics...")
        if 'page_type' not in df.columns:
             return {"Error": "Page type column not found."}

        page_type_metrics = {}
        # Ensure calculation handles potential division by zero if type_pages is 0
        for page_type, group in df.groupby('page_type'):
            type_pages = group['normalized_url'].nunique()
            violations_count = len(group)
            critical_violations = group[group['impact'] == 'critical'].shape[0] # Count rows directly
            critical_pages = group[group['impact'] == 'critical']['normalized_url'].nunique() # Count unique pages with critical issues

            page_type_metrics[page_type] = {
                'Pages': type_pages,
                'Total Violations': violations_count,
                'Avg Violations per Page': round(violations_count / type_pages, 2) if type_pages > 0 else 0,
                'Critical Violations': critical_violations,
                'Critical Pages': critical_pages,
                'Critical Pages (%)': round((critical_pages / type_pages) * 100, 2) if type_pages > 0 else 0
            }
        self.logger.debug("Page type metrics calculation finished.")
        return page_type_metrics

    def _calculate_wcag_metrics(self, df: pd.DataFrame) -> Dict:
        """Calculate WCAG-related metrics, focusing on top issues."""
        self.logger.debug("Calculating WCAG metrics...")
        wcag_metrics = {}
        if not all(col in df.columns for col in ['wcag_category', 'wcag_criterion', 'wcag_name']):
             return {'Top WCAG Issues': {"Error": "WCAG columns not found."}}

        # Group by category, criterion, and name to count occurrences
        wcag_criteria = df.groupby(['wcag_category', 'wcag_criterion', 'wcag_name']).size().reset_index(name='count')
        wcag_criteria = wcag_criteria.sort_values('count', ascending=False)

        top_wcag = {}
        total_violations = len(df)
        for _, row in wcag_criteria.head(5).iterrows():
             # Use a more descriptive key, including the name
            criterion_key = f"{row['wcag_category']} - {row['wcag_name']} ({row['wcag_criterion']})"
            top_wcag[criterion_key] = {
                'count': row['count'],
                'percentage': round((row['count'] / total_violations) * 100, 2) if total_violations > 0 else 0
            }
        wcag_metrics['Top WCAG Issues'] = top_wcag
        self.logger.debug("WCAG metrics calculation finished.")
        return wcag_metrics

    def _calculate_conformance_metrics(self, df: pd.DataFrame, impact_counts: Dict,
                                       unique_pages: int, pages_with_critical: int) -> Dict:
        """
        Calculate a custom WCAG conformance score and level.
        Note: This is a simplified, custom score for indicative purposes.
        Formula: Score = max(0, 100 - min(100, (WeightedViolationScore * FactorA + CriticalPenalty * FactorB)))
        Current Factors: FactorA=2, FactorB=1 (Implicitly via CriticalPenalty definition)
        CriticalPenalty = (% Pages with Critical * PenaltyMultiplier) [Current PenaltyMultiplier=20]
        """
        self.logger.debug("Calculating conformance metrics...")
        metrics = {}
        if unique_pages == 0:
             metrics['WCAG Conformance Score'] = 0
             metrics['WCAG Conformance Level'] = 'N/A (No pages analyzed)'
             return metrics

        # Calculate Weighted Violation Score (average severity points per page)
        weighted_violation_score = (
            (impact_counts.get('critical', 0) * self.impact_weights['critical']) +
            (impact_counts.get('serious', 0) * self.impact_weights['serious']) +
            (impact_counts.get('moderate', 0) * self.impact_weights['moderate']) +
            (impact_counts.get('minor', 0) * self.impact_weights['minor'])
        ) / unique_pages

        # Calculate Critical Factor (% of pages with critical issues)
        critical_factor = pages_with_critical / unique_pages

        # --- Define Conformance Score Parameters (could be configurable) ---
        severity_weight_factor = 2.0 # How much the average severity impacts the score reduction
        critical_penalty_multiplier = 20.0 # How much the % of critical pages impacts the score reduction

        # Calculate penalty based on critical factor
        critical_penalty = critical_factor * critical_penalty_multiplier

        # Calculate total reduction, capping at 100
        total_reduction = min(100, (weighted_violation_score * severity_weight_factor + critical_penalty))

        # Calculate final score (0-100)
        conformance_score = max(0, 100 - total_reduction)
        metrics['WCAG Conformance Score'] = round(conformance_score, 1)

        # Determine Conformance Level based on score thresholds (adjust thresholds as needed)
        if conformance_score >= 95:
            conformance_level = 'AA (Potential)' # Indicate potential, not definitive AA
        elif conformance_score >= 85:
            conformance_level = 'A (Potential)'  # Indicate potential, not definitive A
        elif conformance_score >= 70:
            conformance_level = 'Non-conformant (Minor issues likely)'
        elif conformance_score >= 40:
            conformance_level = 'Non-conformant (Moderate issues likely)'
        else:
            conformance_level = 'Non-conformant (Major issues likely)'
        metrics['WCAG Conformance Level'] = conformance_level

        self.logger.debug(f"Conformance calculation: WgtScore={weighted_violation_score:.2f}, CritFactor={critical_factor:.2f}, CritPenalty={critical_penalty:.2f}, Reduction={total_reduction:.2f}, FinalScore={conformance_score:.1f}")
        return metrics


    def create_aggregations(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        Create various aggregated DataFrames for reporting.

        Args:
            df: Cleaned DataFrame with accessibility data.

        Returns:
            Dictionary where keys are aggregation names and values are DataFrames.
        """
        self.logger.info("Creating data aggregations...")
        aggregations = {}
        total_unique_pages = df['normalized_url'].nunique() # Cache for calculating averages

        # --- Aggregation by Impact ---
        try:
            agg_impact = df.groupby('impact').agg(
                Total_Violations=('violation_id', 'count'),
                Unique_Pages=('normalized_url', 'nunique')
            ).reset_index()

            # Add percentage
            total_violations = agg_impact['Total_Violations'].sum()
            agg_impact['Percentage'] = (agg_impact['Total_Violations'] / total_violations * 100).round(2) if total_violations > 0 else 0

            # Add Average per Page (for this impact level across all pages)
            agg_impact['Avg_Across_All_Pages'] = agg_impact.apply(
                lambda row: round(row['Total_Violations'] / total_unique_pages, 2) if total_unique_pages > 0 else 0, axis=1
            )

            # Sort by severity
            impact_order = {level: i for i, level in enumerate(self.impact_weights.keys())}
            agg_impact = agg_impact.sort_values(by='impact', key=lambda x: x.map(impact_order), ascending=False)

            aggregations['By Impact'] = agg_impact
            self.logger.debug("Created aggregation 'By Impact'.")
        except Exception as e:
            self.logger.error(f"Error creating aggregation 'By Impact': {e}", exc_info=True)
            aggregations['By Impact'] = pd.DataFrame()


        # --- Aggregation by Page ---
        try:
            # Define aggregations dynamically
            agg_funcs = {
                'Total_Violations': pd.NamedAgg(column='violation_id', aggfunc='count'),
                'Page_Type': pd.NamedAgg(column='page_type', aggfunc='first'),
                'Display_URL': pd.NamedAgg(column='page_url', aggfunc='first'), # Keep one original URL for display
            }
            # Add counts for each impact level
            for impact_level in self.impact_weights.keys():
                 agg_funcs[f'{impact_level.capitalize()}_Violations'] = pd.NamedAgg(
                     column='impact', aggfunc=lambda x: (x == impact_level).sum()
                 )
            # Add template if available
            if 'template' in df.columns:
                 agg_funcs['Template'] = pd.NamedAgg(column='template', aggfunc='first')

            agg_page = df.groupby('normalized_url').agg(**agg_funcs).reset_index()

            # Calculate Priority Score per page
            agg_page['Priority_Score'] = sum(
                 agg_page[f'{level.capitalize()}_Violations'] * weight
                 for level, weight in self.impact_weights.items() if level != 'unknown' # Exclude unknown from score
            )

            # Sort by priority score
            agg_page = agg_page.sort_values('Priority_Score', ascending=False)
            aggregations['By Page'] = agg_page
            self.logger.debug("Created aggregation 'By Page'.")
        except Exception as e:
            self.logger.error(f"Error creating aggregation 'By Page': {e}", exc_info=True)
            aggregations['By Page'] = pd.DataFrame()

        # --- Aggregation by Violation Type ---
        try:
            # Only keep the relevant columns for the 'By Violation' table
            agg_funcs_violation = {
                'Total_Occurrences': pd.NamedAgg(column='violation_id', aggfunc='count'),
                'Affected_Pages': pd.NamedAgg(column='normalized_url', aggfunc='nunique'),
                'WCAG_Category': pd.NamedAgg(column='wcag_category', aggfunc='first'),
                'WCAG_Criterion': pd.NamedAgg(column='wcag_criterion', aggfunc='first'),
                'WCAG_Name': pd.NamedAgg(column='wcag_name', aggfunc='first'),
                'Most_Common_Impact': pd.NamedAgg(column='impact', aggfunc=lambda x: x.mode()[0] if not x.mode().empty else 'unknown'),
            }

            agg_violation = df.groupby('violation_id').agg(**agg_funcs_violation).reset_index()

            # Calculate Priority Score per violation type
            impact_weights = self.impact_weights
            def priority_score(row):
                return impact_weights.get(row['Most_Common_Impact'], 0) * row['Total_Occurrences']
            agg_violation['Priority_Score'] = agg_violation.apply(priority_score, axis=1)

            # Add Solution Info
            def get_solution_info(violation_id, field):
                violation_id_lower = violation_id.lower()
                for key, solution_data in self.solution_mapping.items():
                    if key in violation_id_lower:
                        return solution_data.get(field, "N/A")
                if field == 'description': return 'Check WCAG guidelines for this violation'
                if field == 'technical': return 'Refer to WCAG documentation'
                if field == 'impact': return 'May affect users with disabilities'
                return "N/A"

            agg_violation['Solution_Description'] = agg_violation['violation_id'].apply(lambda vid: get_solution_info(vid, 'description'))
            agg_violation['Technical_Solution'] = agg_violation['violation_id'].apply(lambda vid: get_solution_info(vid, 'technical'))
            agg_violation['User_Impact'] = agg_violation['violation_id'].apply(lambda vid: get_solution_info(vid, 'impact'))

            # Calculate percentage based on the total number of violations in the cleaned DataFrame
            total_violations = len(df)
            sum_agg = agg_violation['Total_Occurrences'].sum()
            self.logger.debug(f"[By Violation] total_violations (rows in df): {total_violations}, sum of Total_Occurrences: {sum_agg}")
            agg_violation['Percentage'] = (agg_violation['Total_Occurrences'] / total_violations * 100).round(2) if total_violations > 0 else 0

            # Reorder columns for clarity
            columns_order = [
                'violation_id', 'Most_Common_Impact', 'WCAG_Category', 'WCAG_Criterion', 'WCAG_Name',
                'Total_Occurrences', 'Affected_Pages', 'Priority_Score', 'Percentage',
                'Solution_Description', 'Technical_Solution', 'User_Impact'
            ]
            agg_violation = agg_violation[columns_order]

            # Sort by priority score
            agg_violation = agg_violation.sort_values('Priority_Score', ascending=False)
            aggregations['By Violation'] = agg_violation
            self.logger.debug("Created aggregation 'By Violation'.")
        except Exception as e:
            self.logger.error(f"Error creating aggregation 'By Violation': {e}", exc_info=True)
            aggregations['By Violation'] = pd.DataFrame()


        # --- Aggregation by Page Type ---
        try:
            if 'page_type' not in df.columns:
                 raise KeyError("'page_type' column not found for aggregation.")

            agg_funcs_pagetype = {
                'Total_Pages': pd.NamedAgg(column='normalized_url', aggfunc='nunique'),
                'Total_Violations': pd.NamedAgg(column='violation_id', aggfunc='count'),
                 # Add impact counts per page type
                 **{f'{level.capitalize()}_Violations': pd.NamedAgg(column='impact', aggfunc=lambda x: (x == level).sum())
                   for level in self.impact_weights.keys()},
                'Most_Common_Violation': pd.NamedAgg(column='violation_id', aggfunc=lambda x: x.value_counts().index[0] if not x.empty else "None")
            }

            page_type_agg = df.groupby('page_type').agg(**agg_funcs_pagetype).reset_index()

            # Calculate Avg Violations per Page for this type
            page_type_agg['Avg_Violations_Per_Page'] = page_type_agg.apply(
                 lambda row: round(row['Total_Violations'] / row['Total_Pages'], 2) if row['Total_Pages'] > 0 else 0, axis=1
            )

            # Calculate Priority Score per Page Type (based on average severity per page)
            page_type_agg['Priority_Score'] = page_type_agg.apply(
                 lambda row: sum(row[f'{level.capitalize()}_Violations'] * weight for level, weight in self.impact_weights.items() if level != 'unknown') / row['Total_Pages'] if row['Total_Pages'] > 0 else 0,
                 axis=1
            )

            # Find Top WCAG Category for this page type
            def get_top_wcag_category(page_type_subset):
                 if page_type_subset.empty or 'wcag_category' not in page_type_subset.columns:
                      return "N/A"
                 top_category = page_type_subset['wcag_category'].value_counts()
                 return top_category.index[0] if not top_category.empty else "N/A"

            page_type_agg['Top_WCAG_Category'] = page_type_agg['page_type'].apply(lambda pt: get_top_wcag_category(df[df['page_type'] == pt]))


            # Sort by priority score
            page_type_agg = page_type_agg.sort_values('Priority_Score', ascending=False)
            aggregations['By Page Type'] = page_type_agg
            self.logger.debug("Created aggregation 'By Page Type'.")
        except Exception as e:
             self.logger.error(f"Error creating aggregation 'By Page Type': {e}", exc_info=True)
             aggregations['By Page Type'] = pd.DataFrame()

        # --- Aggregation by Template (if 'template' column exists) ---
        if 'template' in df.columns and df['template'].nunique() > 1: # Only aggregate if templates exist and are varied
             try:
                 # Exclude 'Unknown' template from specific analysis if desired, but keep it for counts
                 template_df_known = df[df['template'] != 'Unknown']

                 if not template_df_known.empty:
                      agg_funcs_template = {
                           'Pages': pd.NamedAgg(column='normalized_url', aggfunc='nunique'),
                           'Total_Violations': pd.NamedAgg(column='violation_id', aggfunc='count'),
                           **{f'{level.capitalize()}_Violations': pd.NamedAgg(column='impact', aggfunc=lambda x: (x == level).sum())
                             for level in self.impact_weights.keys()},
                           'Unique_Violations': pd.NamedAgg(column='violation_id', aggfunc='nunique'),
                           'Top_Violation': pd.NamedAgg(column='violation_id', aggfunc=lambda x: x.value_counts().index[0] if not x.empty else "None"),
                           'Top_WCAG_Category': pd.NamedAgg(column='wcag_category', aggfunc=lambda x: x.value_counts().index[0] if not x.empty else "N/A"),
                      }

                      agg_template = template_df_known.groupby('template').agg(**agg_funcs_template).reset_index()

                      # Calculate Avg Violations Per Page for this template
                      agg_template['Avg_Violations_Per_Page'] = agg_template.apply(
                           lambda row: round(row['Total_Violations'] / row['Pages'], 2) if row['Pages'] > 0 else 0, axis=1
                      )
                      # Calculate Priority Score (average severity per page for this template)
                      agg_template['Priority_Score'] = agg_template.apply(
                           lambda row: sum(row[f'{level.capitalize()}_Violations'] * weight for level, weight in self.impact_weights.items() if level != 'unknown') / row['Pages'] if row['Pages'] > 0 else 0,
                           axis=1
                      )
                      # Sort by priority score
                      agg_template = agg_template.sort_values('Priority_Score', ascending=False)
                      aggregations['By Template'] = agg_template
                      self.logger.debug("Created aggregation 'By Template'.")
                 else:
                      self.logger.info("No data found for known templates, skipping 'By Template' aggregation.")
                      aggregations['By Template'] = pd.DataFrame()

             except Exception as e:
                  self.logger.error(f"Error creating aggregation 'By Template': {e}", exc_info=True)
                  aggregations['By Template'] = pd.DataFrame()
        else:
             self.logger.info("Skipping 'By Template' aggregation: 'template' column not found or only contains 'Unknown'.")
             aggregations['By Template'] = pd.DataFrame()


        # --- Funnel Aggregations (if funnel data exists) ---
        if 'is_in_funnel' in df.columns and df['is_in_funnel'].any():
            funnel_df = df[df['is_in_funnel']].copy()
            try:
                # Aggregation By Funnel
                agg_funcs_funnel = {
                    'Pages': pd.NamedAgg(column='normalized_url', aggfunc='nunique'),
                    'Total_Violations': pd.NamedAgg(column='violation_id', aggfunc='count'),
                    **{f'{level.capitalize()}_Violations': pd.NamedAgg(column='impact', aggfunc=lambda x: (x == level).sum())
                       for level in self.impact_weights.keys()},
                    'Unique_Violations': pd.NamedAgg(column='violation_id', aggfunc='nunique'),
                     # Use funnel_severity_score for weighted calculation
                    'Weighted_Severity_Sum': pd.NamedAgg(column='funnel_severity_score', aggfunc='sum'),
                }
                agg_funnel = funnel_df.groupby('funnel_name').agg(**agg_funcs_funnel).reset_index()

                # Calculate Avg Violations Per Page & Priority Score
                agg_funnel['Avg_Violations_Per_Page'] = agg_funnel.apply(
                     lambda row: round(row['Total_Violations'] / row['Pages'], 2) if row['Pages'] > 0 else 0, axis=1
                )
                agg_funnel['Priority_Score'] = agg_funnel.apply(
                     lambda row: round(row['Weighted_Severity_Sum'] / row['Pages'], 2) if row['Pages'] > 0 else 0, axis=1
                )
                # Find top violation in funnel
                top_violations_funnel = funnel_df.groupby('funnel_name')['violation_id'].agg(lambda x: x.value_counts().index[0] if not x.empty else "None")
                agg_funnel['Top_Violation'] = agg_funnel['funnel_name'].map(top_violations_funnel)

                agg_funnel = agg_funnel.sort_values('Priority_Score', ascending=False)
                aggregations['By Funnel'] = agg_funnel
                self.logger.debug("Created aggregation 'By Funnel'.")

                # Aggregation By Funnel Step
                agg_funcs_step = {
                    'Pages': pd.NamedAgg(column='normalized_url', aggfunc='nunique'),
                    'Total_Violations': pd.NamedAgg(column='violation_id', aggfunc='count'),
                     **{f'{level.capitalize()}_Violations': pd.NamedAgg(column='impact', aggfunc=lambda x: (x == level).sum())
                       for level in self.impact_weights.keys()},
                    'Unique_Violations': pd.NamedAgg(column='violation_id', aggfunc='nunique'),
                    'Weighted_Severity_Sum': pd.NamedAgg(column='funnel_severity_score', aggfunc='sum'),
                }
                # Group by funnel name and step, ignoring 'none' step
                agg_step = funnel_df[funnel_df['funnel_step'] != 'none'].groupby(['funnel_name', 'funnel_step']).agg(**agg_funcs_step).reset_index()

                # Calculate Priority Score per step
                agg_step['Priority_Score'] = agg_step.apply(
                     lambda row: round(row['Weighted_Severity_Sum'] / row['Pages'], 2) if row['Pages'] > 0 else 0, axis=1
                 )
                # Sort by priority score
                agg_step = agg_step.sort_values(['funnel_name', 'Priority_Score'], ascending=[True, False])
                aggregations['By Funnel Step'] = agg_step
                self.logger.debug("Created aggregation 'By Funnel Step'.")

            except Exception as e:
                 self.logger.error(f"Error creating funnel aggregations: {e}", exc_info=True)
                 aggregations['By Funnel'] = pd.DataFrame()
                 aggregations['By Funnel Step'] = pd.DataFrame()
        else:
             self.logger.info("Skipping funnel aggregations as no funnel data was identified.")
             aggregations['By Funnel'] = pd.DataFrame()
             aggregations['By Funnel Step'] = pd.DataFrame()


        self.logger.info("Data aggregation finished.")
        return aggregations


    def create_funnel_charts(self, funnel_metrics: Dict, aggregations: Dict[str, pd.DataFrame], chart_dir: Path) -> Dict[str, str]:
        """Create funnel-specific visualizations."""
        self.logger.info("Creating funnel-specific charts...")
        funnel_chart_files = {}

        # Check if necessary funnel aggregation exists and is not empty
        if 'By Funnel' not in aggregations or aggregations['By Funnel'].empty:
            self.logger.warning("Cannot create funnel charts: 'By Funnel' aggregation is missing or empty.")
            return funnel_chart_files

        funnel_df = aggregations['By Funnel']

        # Define colors
        colors = {
            'critical': '#E63946', 'serious': '#F4A261',
            'moderate': '#2A9D8F', 'minor': '#457B9D', 'unknown': '#BDBDBD'
        }

        # --- Chart 1: Stacked Bar Chart of Violations per Funnel ---
        try:
            plt.figure(figsize=(12, max(6, len(funnel_df) * 0.6))) # Adjust height based on number of funnels
            funnel_names = funnel_df['funnel_name']
            impact_levels = ['Minor', 'Moderate', 'Serious', 'Critical'] # Order for stacking
            bottom = np.zeros(len(funnel_df))

            for level in impact_levels:
                 col_name = f'{level}_Violations'
                 if col_name in funnel_df.columns:
                      values = funnel_df[col_name]
                      plt.barh(funnel_names, values, height=0.6, left=bottom,
                               color=colors.get(level.lower(), '#BDBDBD'), label=level)
                      bottom += values # Update bottom for next stack level
                 else:
                      self.logger.warning(f"Column '{col_name}' not found in 'By Funnel' aggregation for chart.")


            plt.xlabel('Number of Violations')
            plt.ylabel('Funnel Name')
            plt.title('Accessibility Issues by Funnel', fontsize=16)
            plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
            plt.grid(axis='x', linestyle='--', alpha=0.7)
            plt.gca().invert_yaxis() # Show highest priority funnel at top
            plt.tight_layout(rect=[0, 0, 0.9, 1]) # Adjust layout to make space for legend

            chart_path = chart_dir / f'chart_funnel_violations_{self.domain_slug}.png'
            plt.savefig(chart_path, dpi=300, bbox_inches='tight')
            plt.close()
            funnel_chart_files['funnel_violations'] = str(chart_path)
            self.logger.info(f"Created funnel violations chart: {chart_path}")

        except Exception as e:
            self.logger.error(f"Error creating funnel violations bar chart: {e}", exc_info=True)


        # --- Chart 2: Heatmap of Violations by Funnel Step ---
        if 'By Funnel Step' in aggregations and not aggregations['By Funnel Step'].empty:
            step_df = aggregations['By Funnel Step']
            try:
                 # Use 'Priority_Score' for the heatmap value for better insight
                 pivot_df = step_df.pivot_table(
                     index='funnel_name',
                     columns='funnel_step',
                     values='Priority_Score', # Use priority score for heatmap intensity
                     aggfunc='mean', # Use mean score if multiple entries exist (shouldn't happen with groupby)
                     fill_value=0
                 )

                 if not pivot_df.empty and len(step_df) > 1: # Only create heatmap if there's data
                    plt.figure(figsize=(max(10, pivot_df.shape[1] * 1.5), max(6, pivot_df.shape[0] * 0.8))) # Adjust size dynamically

                    sns.heatmap(pivot_df, annot=True, cmap='YlOrRd', fmt=".1f", # Format score to 1 decimal
                                linewidths=0.5, linecolor='black',
                                cbar_kws={'label': 'Average Priority Score per Step'})

                    plt.title('Funnel Step Accessibility Hotspots (by Priority Score)', fontsize=16)
                    plt.ylabel('Funnel Name')
                    plt.xlabel('Funnel Step')
                    plt.xticks(rotation=45, ha='right')
                    plt.yticks(rotation=0)
                    plt.tight_layout()

                    chart_path = chart_dir / f'chart_funnel_steps_heatmap_{self.domain_slug}.png'
                    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                    plt.close()
                    funnel_chart_files['funnel_steps_heatmap'] = str(chart_path)
                    self.logger.info(f"Created funnel steps heatmap chart: {chart_path}")
                 else:
                    self.logger.info("Skipping funnel steps heatmap: Not enough data or pivot failed.")

            except Exception as e:
                 self.logger.error(f"Error creating funnel steps heatmap: {e}", exc_info=True)
        else:
             self.logger.info("Skipping funnel steps heatmap: 'By Funnel Step' aggregation missing or empty.")


        return funnel_chart_files

    def create_charts(self, metrics: Dict, aggregations: Dict[str, pd.DataFrame],
                      data_df: pd.DataFrame) -> Dict[str, str]:
        """
        Create various summary charts for the accessibility report.

        Args:
            metrics: Dictionary of calculated metrics.
            aggregations: Dictionary of aggregation DataFrames.
            data_df: The source DataFrame (needed for some chart types like heatmap).

        Returns:
            Dictionary mapping chart types to their saved file paths.
        """
        # Get charts directory using OutputManager
        if self.output_manager:
            charts_dir = self.output_manager.get_path("charts") # Should create 'analysis/charts'
            charts_dir.mkdir(parents=True, exist_ok=True) # Ensure it exists
        else:
            charts_dir = Path("./charts") # Fallback
            charts_dir.mkdir(exist_ok=True)

        self.logger.info(f"Generating charts in directory: {charts_dir}")
        chart_files = {}

        # Define color palettes
        impact_colors = {
            'critical': '#E63946', 'serious': '#F4A261',
            'moderate': '#2A9D8F', 'minor': '#457B9D', 'unknown': '#BDBDBD'
        }
        wcag_colors = {
            'Perceivable': '#0077B6', 'Operable': '#00B4D8',
            'Understandable': '#90BE6D', 'Robust': '#F9C74F', 'Other': '#ADADAD'
        }

        # Set plot style
        try:
             plt.style.use('seaborn-v0_8-whitegrid')
             sns.set_style("whitegrid")
        except:
             plt.style.use('seaborn-whitegrid') # Fallback for older matplotlib
             sns.set_style("whitegrid")
        plt.rcParams['figure.dpi'] = 120 # Slightly lower DPI for potentially faster generation
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans'] # Common sans-serif fonts
        plt.rcParams['axes.labelsize'] = 11
        plt.rcParams['axes.titlesize'] = 14
        plt.rcParams['xtick.labelsize'] = 9
        plt.rcParams['ytick.labelsize'] = 9
        plt.rcParams['legend.fontsize'] = 9


        # --- Chart 1: Donut chart for impact distribution ---
        if 'By Impact' in aggregations and not aggregations['By Impact'].empty:
             try:
                 fig, ax = plt.subplots(figsize=(8, 6)) # Adjusted size
                 impact_df = aggregations['By Impact'].copy()
                 # Filter out 'unknown' if count is 0? Optional.
                 # impact_df = impact_df[impact_df['Total_Violations'] > 0]

                 labels = impact_df['impact']
                 sizes = impact_df['Total_Violations']
                 chart_colors = [impact_colors.get(i, '#BDBDBD') for i in labels]

                 wedges, texts, autotexts = ax.pie(
                     sizes,
                     autopct=lambda pct: f"{pct:.1f}%\n({int(round(pct/100*sum(sizes)))})" if pct > 2 else '', # Show count in autopct
                     startangle=90,
                     wedgeprops={'width': 0.4, 'edgecolor': 'w', 'linewidth': 1}, # Slightly thinner donut
                     colors=chart_colors,
                     pctdistance=0.8 # Move percentage text closer to center
                 )

                 for text in autotexts:
                     text.set_color('white')
                     text.set_fontweight('bold')
                     text.set_fontsize(8)

                 # Center text
                 center_circle = plt.Circle((0, 0), 0.6, fc='white') # 1 - width = 0.6
                 ax.add_patch(center_circle)
                 total_violations = sum(sizes)
                 ax.text(0, 0, f"{total_violations}\nTotal\nViolations",
                         ha='center', va='center', fontsize=12, fontweight='bold')

                 # Legend
                 legend_labels = [f"{row['impact'].capitalize()} ({row['Total_Violations']}, {row['Percentage']:.1f}%)"
                                  for _, row in impact_df.iterrows()]
                 ax.legend(wedges, legend_labels, title="Impact Level",
                           loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))

                 plt.title('Violations by Impact Level', fontsize=14)
                 plt.tight_layout(rect=[0, 0, 0.85, 1]) # Adjust layout for legend
                 chart_path = charts_dir / f'chart_impact_{self.domain_slug}.png'
                 plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                 plt.close(fig)
                 chart_files['impact'] = str(chart_path)
                 self.logger.info(f"Created impact chart: {chart_path}")
             except Exception as e:
                 self.logger.error(f"Error creating impact donut chart: {e}", exc_info=True)


        # --- Chart 2: Bar chart for top problematic pages ---
        if 'By Page' in aggregations and not aggregations['By Page'].empty:
            try:
                 # Select top N pages based on Priority Score
                 top_n = 15
                 pages_df = aggregations['By Page'].head(top_n).copy()
                 pages_df = pages_df.sort_values('Priority_Score', ascending=True) # Ascending for horizontal bar chart

                 fig, ax = plt.subplots(figsize=(10, max(6, len(pages_df) * 0.5))) # Adjust height

                 # Create labels with URL and Page Type
                 labels = [f"{row['Display_URL'][:70]}{'...' if len(row['Display_URL'])>70 else ''}\n[{row['Page_Type']}]"
                           for _, row in pages_df.iterrows()]

                 # Stacked bar chart
                 impact_levels = ['Minor', 'Moderate', 'Serious', 'Critical'] # Order for stacking
                 bottom = np.zeros(len(pages_df))
                 for level in impact_levels:
                      col_name = f'{level}_Violations'
                      if col_name in pages_df.columns:
                           values = pages_df[col_name]
                           ax.barh(labels, values, height=0.6, left=bottom,
                                    color=impact_colors.get(level.lower(), '#BDBDBD'), label=level, # Use level.lower() here too
                                    edgecolor='white', linewidth=0.5)
                           bottom += values
                      else:
                           self.logger.warning(f"Column '{col_name}' not found in 'By Page' aggregation for chart.")


                 # Add annotations (Total Violations & Priority Score)
                 for i, (total, score) in enumerate(zip(pages_df['Total_Violations'], pages_df['Priority_Score'])):
                     ax.text(bottom[i] + 0.5, i, f"Total: {total} | Score: {score:.1f}",
                             va='center', ha='left', fontweight='bold', fontsize=8)


                 ax.set_title(f'Top {top_n} Problematic Pages by Severity Score', fontsize=14)
                 ax.set_xlabel('Number of Violations', fontsize=11)
                 ax.set_ylabel('Page URL [Type]', fontsize=11)

                 legend = ax.legend(title="Severity Level", loc='lower right', frameon=True, framealpha=0.9, edgecolor='gray')
                 legend.get_title().set_fontweight('bold')

                 plt.grid(axis='x', linestyle='--', alpha=0.7)
                 plt.tight_layout()
                 chart_path = charts_dir / f'chart_top_pages_{self.domain_slug}.png'
                 plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                 plt.close(fig)
                 chart_files['top_pages'] = str(chart_path)
                 self.logger.info(f"Created top pages chart: {chart_path}")
            except Exception as e:
                 self.logger.error(f"Error creating top pages bar chart: {e}", exc_info=True)


        # --- Chart 3: Bar chart for top violation types ---
        if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
             try:
                 # Select top N violations based on Priority Score
                 top_n = 15
                 violations_df = aggregations['By Violation'].head(top_n).copy()
                 violations_df = violations_df.sort_values('Priority_Score', ascending=True) # Ascending for horizontal bar

                 fig, ax = plt.subplots(figsize=(10, max(6, len(violations_df) * 0.5)))

                 # Create labels with Violation ID and WCAG Ref
                 labels = [f"{row['violation_id']}\n[{row['WCAG_Category']} {row['WCAG_Criterion']}]"
                           for _, row in violations_df.iterrows()]

                 # Use color based on Most_Common_Impact
                 bar_colors = [impact_colors.get(impact, '#BDBDBD') for impact in violations_df['Most_Common_Impact']]

                 bars = ax.barh(
                     labels,
                     violations_df['Total_Occurrences'],
                     color=bar_colors,
                     alpha=0.9,
                     edgecolor='white',
                     linewidth=0.5
                 )

                 # Add annotations (Percentage & Affected Pages)
                 for i, bar in enumerate(bars):
                     width = bar.get_width()
                     affected_pages = violations_df.iloc[i]['Affected_Pages']
                     percentage = violations_df.iloc[i]['Percentage']
                     score = violations_df.iloc[i]['Priority_Score']
                     ax.text(width + 0.5, bar.get_y() + bar.get_height()/2,
                             f"{percentage:.1f}% ({affected_pages} pages) | Score: {score:.1f}",
                             va='center', ha='left', fontweight='bold', fontsize=8)

                 ax.set_title(f'Top {top_n} Violation Types by Severity Score', fontsize=14)
                 ax.set_xlabel('Number of Occurrences', fontsize=11)
                 ax.set_ylabel('Violation ID [WCAG Ref]', fontsize=11)

                 # *** CORRECTION HERE ***
                 # Custom legend for impact colors
                 impact_levels = ['Minor', 'Moderate', 'Serious', 'Critical'] # List for legend labels
                 # Use k.lower() to access the impact_colors dictionary
                 handles = [plt.Rectangle((0,0),1,1, color=impact_colors[k.lower()]) for k in impact_levels]
                 legend = ax.legend(
                     handles,
                     impact_levels, # Use capitalized names for legend labels
                     title="Most Common Impact",
                     loc='lower right',
                     frameon=True,
                     framealpha=0.9
                 )
                 legend.get_title().set_fontweight('bold')
                 # *** FINE CORREZIONE ***

                 plt.grid(axis='x', linestyle='--', alpha=0.7)
                 plt.tight_layout()
                 chart_path = charts_dir / f'chart_violation_types_{self.domain_slug}.png'
                 plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                 plt.close(fig)
                 chart_files['violation_types'] = str(chart_path)
                 self.logger.info(f"Created violation types chart: {chart_path}")
             except Exception as e:
                 # Log the actual error encountered
                 self.logger.error(f"Error creating violation types bar chart: {e}", exc_info=True)


        # --- Chart 4: Bar chart for WCAG principle distribution ---
        if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
             try:
                 wcag_df = aggregations['By Violation'].copy()
                 # Sum violations per WCAG category
                 wcag_counts = wcag_df.groupby('WCAG_Category')[['Total_Occurrences']].sum().reset_index()
                 wcag_counts = wcag_counts.sort_values('Total_Occurrences', ascending=True) # Ascending for horizontal bar

                 fig, ax = plt.subplots(figsize=(8, 5))
                 bar_colors = [wcag_colors.get(cat, '#ADADAD') for cat in wcag_counts['WCAG_Category']]

                 bars = ax.barh(
                     wcag_counts['WCAG_Category'],
                     wcag_counts['Total_Occurrences'],
                     color=bar_colors,
                     edgecolor='white',
                     linewidth=0.8,
                     height=0.7
                 )

                 # Add annotations (Count & Percentage)
                 total = wcag_counts['Total_Occurrences'].sum()
                 for i, bar in enumerate(bars):
                     count = wcag_counts.iloc[i]['Total_Occurrences']
                     percentage = (count / total * 100) if total > 0 else 0
                     ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                             f"{count:,} ({percentage:.1f}%)", # Format count with comma
                             va='center', ha='left', fontsize=9)

                 ax.set_title('Violations by WCAG Principle', fontsize=14)
                 ax.set_xlabel('Number of Violations', fontsize=11)
                 ax.set_ylabel('WCAG Principle', fontsize=11)

                 plt.grid(axis='x', linestyle='--', alpha=0.7)
                 plt.tight_layout()
                 chart_path = charts_dir / f'chart_wcag_categories_{self.domain_slug}.png'
                 plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                 plt.close(fig)
                 chart_files['wcag_categories'] = str(chart_path)
                 self.logger.info(f"Created WCAG categories chart: {chart_path}")
             except Exception as e:
                 self.logger.error(f"Error creating WCAG categories bar chart: {e}", exc_info=True)


        # --- Chart 5: Heatmap for page type vs impact ---
        if 'By Page Type' in aggregations and not aggregations['By Page Type'].empty and not data_df.empty:
             try:
                  # Pivot data: Page Type vs Impact, value = Avg Violations per Page for that combo
                  heatmap_pivot = data_df.groupby(['page_type', 'impact']).agg(
                       num_violations=pd.NamedAgg(column='violation_id', aggfunc='count')
                  ).reset_index()

                  # Get total pages per page_type for normalization
                  pages_per_type = data_df.groupby('page_type')['normalized_url'].nunique()
                  heatmap_pivot['total_pages_in_type'] = heatmap_pivot['page_type'].map(pages_per_type)

                  # Calculate violations per page for this specific impact/type combo
                  heatmap_pivot['violations_per_page'] = heatmap_pivot.apply(
                       lambda row: row['num_violations'] / row['total_pages_in_type'] if row['total_pages_in_type'] > 0 else 0, axis=1
                  )

                  # Create the pivot table for the heatmap
                  heatmap_table = heatmap_pivot.pivot_table(
                       index='page_type',
                       columns='impact',
                       values='violations_per_page',
                       fill_value=0
                  )

                  # Reorder columns by severity
                  ordered_columns = [col for col in impact_colors if col in heatmap_table.columns]
                  heatmap_table = heatmap_table[ordered_columns]


                  if not heatmap_table.empty and len(heatmap_table) > 1:
                      plt.figure(figsize=(max(8, len(ordered_columns)*1.5), max(6, len(heatmap_table)*0.6))) # Dynamic size
                      cmap = sns.color_palette("YlOrRd", as_cmap=True) # Yellow-Orange-Red colormap

                      ax = sns.heatmap(
                          heatmap_table,
                          annot=True,
                          fmt=".2f", # Format to 2 decimal places
                          cmap=cmap,
                          linewidths=.5,
                          linecolor='grey',
                          cbar_kws={'label': 'Average Violations per Page'}
                      )

                      plt.title('Avg Violations per Page: Page Type vs Impact', fontsize=14)
                      plt.ylabel('Page Type', fontsize=11)
                      plt.xlabel('Impact Level', fontsize=11)
                      plt.xticks(rotation=0)
                      plt.yticks(rotation=0) # Keep page types horizontal
                      plt.tight_layout()
                      chart_path = charts_dir / f'chart_page_type_heatmap_{self.domain_slug}.png'
                      plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                      plt.close()
                      chart_files['page_type_heatmap'] = str(chart_path)
                      self.logger.info(f"Created page type heatmap chart: {chart_path}")
                  else:
                      self.logger.info("Skipping page type heatmap: Not enough data or pivot failed.")
             except Exception as e:
                  self.logger.error(f"Error creating page type heatmap: {e}", exc_info=True)


        # --- Chart 6: Template Analysis Chart (if template data available) ---
        if 'By Template' in aggregations and not aggregations['By Template'].empty:
            try:
                template_agg_df = aggregations['By Template'].copy()
                # Select top N templates by priority score
                top_n_templates = 15
                template_df_chart = template_agg_df.head(top_n_templates).sort_values('Priority_Score', ascending=True)

                fig, ax1 = plt.subplots(figsize=(10, max(6, len(template_df_chart) * 0.5)))

                # Bar chart for Average Violations per Page
                bar_colors = plt.cm.viridis(np.linspace(0.3, 0.9, len(template_df_chart))) # Viridis color map
                bars = ax1.barh(
                    template_df_chart['template'],
                    template_df_chart['Avg_Violations_Per_Page'],
                    color=bar_colors,
                    alpha=0.8,
                    edgecolor='white',
                    linewidth=0.5,
                    height=0.7
                )
                ax1.set_xlabel('Average Violations per Page', fontsize=11, color='darkblue')
                ax1.set_ylabel('Template ID', fontsize=11)
                ax1.tick_params(axis='x', labelcolor='darkblue')
                ax1.grid(axis='x', linestyle='--', alpha=0.7)

                # Line chart for Priority Score on secondary axis
                ax2 = ax1.twiny() # Share y-axis (template names)
                ax2.plot(
                    template_df_chart['Priority_Score'],
                    template_df_chart['template'],
                    'ro-', # Red line with circle markers
                    linewidth=2,
                    markersize=5,
                    alpha=0.7,
                    label='Priority Score'
                )
                ax2.set_xlabel('Priority Score (Avg Severity per Page)', fontsize=11, color='red')
                ax2.tick_params(axis='x', labelcolor='red')

                # Add annotations for avg violations
                for i, bar in enumerate(bars):
                    ax1.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                            f"{bar.get_width():.1f}", ha='left', va='center', fontsize=8, color='darkblue')
                # Add annotations for priority score
                for i, score in enumerate(template_df_chart['Priority_Score']):
                     ax2.text(score + 0.1, template_df_chart['template'].iloc[i],
                             f"{score:.1f}", ha='left', va='bottom', fontsize=8, color='red')


                plt.title(f'Top {top_n_templates} Templates: Avg Violations & Priority Score', fontsize=14)
                # Ensure y-axis labels are visible
                plt.subplots_adjust(left=0.3) # Adjust left margin if template names are long
                plt.tight_layout()
                chart_path = charts_dir / f'chart_template_analysis_{self.domain_slug}.png'
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                plt.close(fig)
                chart_files['template_analysis'] = str(chart_path)
                self.logger.info(f"Created template analysis chart: {chart_path}")
            except Exception as e:
                 self.logger.error(f"Error creating template analysis chart: {e}", exc_info=True)


        # --- Funnel-specific visualizations ---
        # Call create_funnel_charts only if funnel analysis was performed
        if 'Funnel Analysis' in metrics and metrics['Funnel Analysis'].get('Total Funnels Identified', 0) > 0:
             funnel_chart_files = self.create_funnel_charts(metrics.get('Funnel Analysis', {}), aggregations, charts_dir)
             chart_files.update(funnel_chart_files) # Add funnel charts to the main dictionary
        else:
             self.logger.info("Skipping funnel chart generation as no funnel data was processed.")

        self.logger.info(f"Chart generation finished. Created {len(chart_files)} charts.")
        return chart_files
    
    
    # load_template_data and analyze_templates seem specific to a workflow
    # where template analysis *requires* the pickle file and projects violations.
    # Kept separate for clarity, but ensure they handle missing PKL gracefully.
    def load_template_data_from_pkl(self, pickle_file: str) -> Tuple[pd.DataFrame, Dict]:
        """
        Load template structure data specifically from a crawler state pickle file.
        This is used for the projection-based template analysis.

        Args:
            pickle_file: Path to the crawler state pickle file.

        Returns:
            Tuple of (templates DataFrame for analysis, raw state dictionary).
            Returns empty DataFrame if file not found or invalid.
        """
        self.logger.info(f"Loading template structures for projection analysis from: {pickle_file}")
        pkl_path = Path(pickle_file)
        if not pkl_path.exists():
            self.logger.warning(f"Template pickle file for projection analysis not found: {pickle_file}. Returning empty.")
            return pd.DataFrame(), {}

        try:
            with open(pkl_path, "rb") as f:
                state = pickle.load(f)

            structures = {}
             # Detect state format (similar to _integrate_crawler_data)
            if isinstance(state, dict) and "domain_data" in state and isinstance(state["domain_data"], dict):
                 found_domain_data = False
                 for domain_key, domain_data in state["domain_data"].items():
                     if isinstance(domain_data, dict) and self.domain_slug in domain_key.lower():
                         structures = domain_data.get("structures", {})
                         found_domain_data = True
                         break
                 if not found_domain_data:
                      self.logger.warning(f"Could not find data for domain slug '{self.domain_slug}' in multi-domain state file for template analysis.")
            elif isinstance(state, dict) and "structures" in state:
                 structures = state.get("structures", {})
            else:
                 self.logger.warning(f"Unrecognized state format in {pickle_file}. Cannot extract structures for projection.")
                 return pd.DataFrame(), state # Return empty DF but original state

            if not structures:
                 self.logger.warning("No 'structures' data found in the loaded state for projection analysis.")
                 return pd.DataFrame(), state


            templates_for_analysis = []
            for template_id, data in structures.items():
                 # Need representative URL and list of all URLs for count
                 urls_in_template = []
                 rep_url = ''
                 if isinstance(data, dict):
                     urls_in_template = data.get('urls', []) or data.get('url_list', [])
                     rep_url = data.get('url', urls_in_template[0] if urls_in_template else '') # Take first URL if 'url' key missing
                     if rep_url and rep_url not in urls_in_template:
                          urls_in_template.append(rep_url) # Ensure rep_url is in the list
                 elif isinstance(data, list):
                      urls_in_template = data
                      rep_url = urls_in_template[0] if urls_in_template else ''

                 if not rep_url or not urls_in_template:
                      #self.logger.debug(f"Skipping template '{template_id}' for projection analysis: missing representative URL or URL list.")
                      continue

                 templates_for_analysis.append({
                     'Template': template_id,
                     'Representative_URL': rep_url,
                     'Normalized_Rep_URL': self.normalize_url(rep_url),
                     'Occurrence_Count': len(urls_in_template), # Count based on URLs in state
                     'All_Template_Pages': urls_in_template, # Keep the list if needed later
                     'Template_Depth': data.get('depth', 0) if isinstance(data, dict) else 0
                 })

            templates_df = pd.DataFrame(templates_for_analysis)

            if not templates_df.empty:
                 # Filter out templates with no representative URL (shouldn't happen with above logic)
                 templates_df = templates_df.dropna(subset=['Normalized_Rep_URL'])
                 # Sort by occurrence count
                 templates_df = templates_df.sort_values('Occurrence_Count', ascending=False)
                 self.logger.info(f"Processed {len(templates_df)} templates for projection analysis.")
            else:
                 self.logger.warning("No valid templates found for projection analysis after processing.")

            return templates_df, state

        except Exception as e:
            self.logger.error(f"Error loading template data from {pickle_file} for projection: {e}", exc_info=True)
            return pd.DataFrame(), {} # Return empty on error


    def analyze_templates_projection(self, templates_df: pd.DataFrame, axe_df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyzes templates by projecting violations found on a representative page
        across all pages sharing that template (based on crawler state).

        Args:
            templates_df: DataFrame from load_template_data_from_pkl.
            axe_df: DataFrame with accessibility data (violations).

        Returns:
            DataFrame with template projection analysis, or empty DataFrame if input is invalid.
        """
        self.logger.info("Analyzing templates using projection method...")
        if templates_df.empty or 'Normalized_Rep_URL' not in templates_df.columns:
            self.logger.warning("Template DataFrame for projection is empty or missing required columns. Skipping analysis.")
            return pd.DataFrame(columns=[
                'Template', 'Representative_URL', 'Occurrence_Count', 'Sample_Violations',
                'Projected_Total', 'Projected_Critical', 'Projected_Serious',
                'Projected_Moderate', 'Projected_Minor', 'Priority_Score', 'Criticality', 'Note'
            ]) # Return empty DF with expected columns
        if axe_df.empty:
             self.logger.warning("Axe data DataFrame is empty. Cannot perform template projection analysis.")
             return pd.DataFrame(columns=[
                 'Template', 'Representative_URL', 'Occurrence_Count', 'Sample_Violations',
                 'Projected_Total', 'Projected_Critical', 'Projected_Serious',
                 'Projected_Moderate', 'Projected_Minor', 'Priority_Score', 'Criticality', 'Note'
             ])

        # Ensure axe_df has normalized URLs for matching
        if 'normalized_url' not in axe_df.columns:
             self.logger.warning("Normalizing URLs in axe_df for template matching.")
             axe_df['normalized_url'] = axe_df['page_url'].apply(self.normalize_url)


        template_results = []
        # Use ThreadPoolExecutor for potentially faster analysis if many templates
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
             futures = {executor.submit(self._analyze_single_template_projection, row, axe_df): row for _, row in templates_df.iterrows()}
             for future in futures:
                  try:
                      result = future.result()
                      if result:
                           template_results.append(result)
                  except Exception as e:
                       template_id = futures[future]['Template'] # Get template ID from original row
                       self.logger.error(f"Error analyzing template '{template_id}' projection: {e}", exc_info=True)

        result_df = pd.DataFrame(template_results)
        if not result_df.empty:
            result_df = result_df.sort_values('Priority_Score', ascending=False)
            self.logger.info(f"Template projection analysis complete: {len(result_df)} templates processed.")
        else:
             self.logger.warning("Template projection analysis yielded no results.")

        return result_df


    def _analyze_single_template_projection(self, template_row: pd.Series, axe_df: pd.DataFrame) -> Optional[Dict]:
        """
        Helper function to analyze a single template row using the projection method.

        Args:
            template_row: A row from the templates DataFrame (from load_template_data_from_pkl).
            axe_df: DataFrame with accessibility violations.

        Returns:
            Dictionary with analysis data for the template, or None if invalid.
        """
        template_name = template_row['Template']
        rep_url = template_row['Representative_URL']
        norm_rep_url = template_row['Normalized_Rep_URL']
        occurrence = template_row['Occurrence_Count']

        if not norm_rep_url or occurrence == 0:
             #self.logger.debug(f"Skipping template '{template_name}': No normalized rep URL or zero occurrences.")
             return None

        # Find violations associated with the *representative* URL for this template
        rep_violations_df = axe_df[axe_df['normalized_url'] == norm_rep_url]
        sample_violation_count = len(rep_violations_df)

        # Get impact counts from the representative page's violations
        impact_counts_sample = rep_violations_df['impact'].value_counts().to_dict()

        # Project these counts across all occurrences
        projected_total = sample_violation_count * occurrence
        projected_critical = impact_counts_sample.get('critical', 0) * occurrence
        projected_serious = impact_counts_sample.get('serious', 0) * occurrence
        projected_moderate = impact_counts_sample.get('moderate', 0) * occurrence
        projected_minor = impact_counts_sample.get('minor', 0) * occurrence

        # Calculate priority score based on *projected* severity per occurrence
        # This represents the average severity impact *expected* from this template across the site
        if occurrence > 0:
            # Calculate total projected severity points
            total_projected_severity_points = (
                 projected_critical * self.impact_weights['critical'] +
                 projected_serious * self.impact_weights['serious'] +
                 projected_moderate * self.impact_weights['moderate'] +
                 projected_minor * self.impact_weights['minor']
            )
            # Average score per occurrence
            priority_score = total_projected_severity_points / occurrence
        else:
            priority_score = 0

        # Determine criticality level based on the calculated priority score
        # Thresholds can be adjusted
        if priority_score >= IMPACT_WEIGHTS['serious']: # e.g., avg score >= serious level
            criticality = "High"
        elif priority_score >= IMPACT_WEIGHTS['moderate']: # e.g., avg score >= moderate level
            criticality = "Medium"
        else:
            criticality = "Low"

        # Return results
        return {
            'Template': template_name,
            'Representative_URL': rep_url,
            'Occurrence_Count': occurrence,
            'Sample_Violations': sample_violation_count, # Violations on the single analyzed page
            'Projected_Total': projected_total,
            'Projected_Critical': projected_critical,
            'Projected_Serious': projected_serious,
            'Projected_Moderate': projected_moderate,
            'Projected_Minor': projected_minor,
            'Priority_Score': round(priority_score, 2), # Average projected severity per page
            'Criticality': criticality,
             'Note': "Projected values estimate total impact based on violations found on the representative URL multiplied by the template's occurrence count."
        }


    def generate_report(self, axe_df: pd.DataFrame, metrics: Dict,
                      aggregations: Dict[str, pd.DataFrame], chart_files: Dict[str, str],
                      template_projection_df: Optional[pd.DataFrame] = None, # Renamed for clarity
                      output_excel: Optional[str] = None) -> str:
        """
        Generate a comprehensive Excel report with improved presentation and structure.

        Args:
            axe_df: DataFrame with raw accessibility data.
            metrics: Dictionary of calculated metrics.
            aggregations: Dictionary of aggregation DataFrames.
            chart_files: Dictionary of chart file paths.
            template_projection_df: Optional DataFrame with template projection analysis results.
            output_excel: Path to output Excel file. If None, uses OutputManager.

        Returns:
            Path to the generated Excel file.
        """
        # Determine output path using OutputManager or default
        if self.output_manager and output_excel is None:
            output_excel = str(self.output_manager.get_path(
                 "analysis", f"final_analysis_{self.output_manager.domain_slug}.xlsx"))
            # Optionally backup existing report
            if Path(output_excel).exists() and hasattr(self.output_manager, 'backup_existing_file'):
                 try:
                      backup_path = self.output_manager.backup_existing_file(
                           "analysis", Path(output_excel).name)
                      if backup_path:
                           self.logger.info(f"Backed up existing report to {backup_path}")
                 except Exception as backup_err:
                      self.logger.warning(f"Could not back up existing report: {backup_err}")
        elif output_excel is None:
             # Fallback if no OutputManager and no path provided
             output_excel = f"./final_analysis_{self.domain_slug}.xlsx"

        output_excel_path = Path(output_excel)
        self.logger.info(f"Generating Excel report: {output_excel_path}")

        # Log aggregation sizes for debugging
        for name, df_agg in aggregations.items():
             if isinstance(df_agg, pd.DataFrame):
                  self.logger.debug(f"Aggregation '{name}': {len(df_agg)} rows, Columns: {list(df_agg.columns)}")
             else:
                  self.logger.warning(f"Aggregation '{name}' is not a DataFrame.")


        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        try:
            with pd.ExcelWriter(output_excel_path, engine='xlsxwriter') as writer:
                workbook = writer.book

                # --- Define Excel Formats --- (Add more as needed)
                title_format = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#4472C4', 'font_color': 'white', 'border': 1, 'text_wrap': True})
                subtitle_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'left', 'bg_color': '#D9E1F2', 'border': 1, 'text_wrap': True})
                header_format = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
                cell_format = workbook.add_format({'border': 1, 'valign': 'top', 'text_wrap': True, 'align': 'left'})
                cell_center_format = workbook.add_format({'border': 1, 'valign': 'vcenter', 'text_wrap': True, 'align': 'center'})
                cell_right_format = workbook.add_format({'border': 1, 'valign': 'top', 'text_wrap': True, 'align': 'right'})
                num_format = workbook.add_format({'num_format': '#,##0', 'align': 'right', 'border': 1, 'valign': 'top'})
                num_dec_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'border': 1, 'valign': 'top'})
                percent_format = workbook.add_format({'num_format': '0.0%', 'align': 'right', 'border': 1, 'valign': 'top'})
                metric_name_format = workbook.add_format({'bold': True, 'align': 'left', 'border': 1, 'valign': 'top'})
                metric_value_format = workbook.add_format({'align': 'right', 'border': 1, 'valign': 'top', 'num_format': '#,##0.00'})
                critical_bg_format = workbook.add_format({'bg_color': '#FFCCCC', 'border': 1, 'valign': 'top', 'text_wrap': True}) # Red background
                serious_bg_format = workbook.add_format({'bg_color': '#FFDEAD', 'border': 1, 'valign': 'top', 'text_wrap': True}) # Orange/yellow background
                moderate_bg_format = workbook.add_format({'bg_color': '#C6EFCE', 'border': 1, 'valign': 'top', 'text_wrap': True}) # Light green background
                minor_bg_format = workbook.add_format({'bg_color': '#E0FFFF', 'border': 1, 'valign': 'top', 'text_wrap': True}) # Light blue background
                note_format = workbook.add_format({'italic': True, 'font_color': '#595959', 'font_size': 9})
                link_format = workbook.add_format({'font_color': 'blue', 'underline': 1, 'valign': 'top', 'text_wrap': True})


                # --- Helper function to write DataFrames ---
                def write_df_to_excel(ws, dataframe, start_row, title, subtitle=None, max_cols=20):
                    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
                        self.logger.warning(f"Skipping empty or invalid DataFrame for section: {title}")
                        ws.merge_range(f'A{start_row}:G{start_row}', f"{title} - No Data Available", subtitle_format)
                        return start_row + 2 # Skip some rows

                    self.logger.debug(f"Writing DataFrame '{title}' ({len(dataframe)} rows) to Excel at row {start_row}")
                    ws.merge_range(f'A{start_row}:G{start_row}', title, subtitle_format)
                    current_row = start_row + 1
                    if subtitle:
                         ws.merge_range(f'A{current_row}:G{current_row}', subtitle, note_format)
                         current_row += 1

                    cols_to_write = dataframe.columns[:max_cols]
                    for c_idx, col_name in enumerate(cols_to_write):
                         col_width = 15 # Default width
                         if "URL" in col_name or "Template" in col_name or "element" in col_name.lower(): col_width = 40
                         elif "Solution" in col_name or "Description" in col_name or "Impact" in col_name: col_width = 35
                         elif "Count" in col_name or "Violation" in col_name: col_width = 12
                         ws.set_column(c_idx, c_idx, col_width)
                         ws.write(current_row, c_idx, col_name.replace('_', ' ').title(), header_format)

                    current_row += 1

                    # Apply alternating row colors later if needed, focus on content first
                    for r_idx, (_, row_data) in enumerate(dataframe.iterrows()):
                         for c_idx, col_name in enumerate(cols_to_write):
                              value = row_data.get(col_name, "N/A")
                              fmt = cell_format # Default format

                              # Apply specific formatting based on column name or value type
                              if isinstance(value, (int, float)):
                                   if pd.isna(value): value = "N/A"; fmt = cell_center_format
                                   elif "Percentage" in col_name or ("%" in col_name): fmt = percent_format
                                   elif value == 0: fmt = num_format # Show 0 without decimals
                                   elif abs(value) < 1: fmt = num_dec_format # Small decimals
                                   elif abs(value) < 100 and isinstance(value, float) : fmt = num_dec_format # Decimals for scores etc.
                                   else: fmt = num_format # Large integers
                              elif isinstance(value, str) and value.startswith(('http:', 'https:')):
                                   fmt = link_format # Basic link format
                              elif col_name == 'Impact': # Color based on impact level
                                   val_lower = str(value).lower()
                                   if val_lower == 'critical': fmt = workbook.add_format({'bg_color': '#FFCCCC', 'border': 1, 'bold':True, 'align': 'center', 'valign':'vcenter'})
                                   elif val_lower == 'serious': fmt = workbook.add_format({'bg_color': '#FFDEAD', 'border': 1, 'align': 'center', 'valign':'vcenter'})
                                   elif val_lower == 'moderate': fmt = workbook.add_format({'bg_color': '#C6EFCE', 'border': 1, 'align': 'center', 'valign':'vcenter'})
                                   elif val_lower == 'minor': fmt = workbook.add_format({'bg_color': '#E0FFFF', 'border': 1, 'align': 'center', 'valign':'vcenter'})
                                   else: fmt = cell_center_format
                              elif col_name == 'Criticality': # Color based on template criticality
                                   val_lower = str(value).lower()
                                   if val_lower == 'high': fmt = workbook.add_format({'bg_color': '#FFCCCC', 'border': 1, 'bold':True, 'align': 'center', 'valign':'vcenter'})
                                   elif val_lower == 'medium': fmt = workbook.add_format({'bg_color': '#FFDEAD', 'border': 1, 'align': 'center', 'valign':'vcenter'})
                                   else: fmt = cell_center_format # Low or N/A

                              # Write cell value with determined format
                              try:
                                   if isinstance(value, (int, float)) and not pd.isna(value):
                                       ws.write_number(current_row + r_idx, c_idx, value, fmt)
                                   elif isinstance(value, str) and value.startswith(('http:', 'https:')):
                                        ws.write_url(current_row + r_idx, c_idx, value, fmt, string=value[:255]) # Limit URL string length
                                   else:
                                        # Limit string length to avoid Excel errors
                                        ws.write_string(current_row + r_idx, c_idx, str(value)[:32767], fmt)
                              except Exception as write_err:
                                   self.logger.error(f"Error writing cell ({current_row + r_idx}, {c_idx}) for '{title}': {write_err}. Value: {str(value)[:100]}")
                                   ws.write_string(current_row + r_idx, c_idx, "WriteError", cell_format)

                    # Freeze top row (headers)
                    ws.freeze_panes(current_row, 0)
                    # Add autofilter
                    ws.autofilter(current_row -1 , 0, current_row + len(dataframe) - 1, len(cols_to_write) - 1)

                    return current_row + len(dataframe) + 1 # Return next available row index


                # --- 1. Executive Summary Worksheet ---
                summary_ws = workbook.add_worksheet('Executive Summary')
                summary_ws.set_column('A:A', 30) # Metric Name
                summary_ws.set_column('B:B', 18) # Value
                summary_ws.set_column('C:C', 50) # Description / Chart Placeholder
                summary_ws.set_column('D:G', 15) # Placeholder for potential future use

                summary_ws.merge_range('A1:D1', f'Accessibility Analysis Report - {self.domain_slug}', title_format)
                summary_ws.merge_range('A2:D2', f'Analysis Date: {timestamp}', cell_center_format)

                current_row = 4

                # KPI Section
                summary_ws.merge_range(f'A{current_row}:B{current_row}', 'Key Performance Indicators', subtitle_format)
                current_row += 1
                kpi_data = [
                     ("WCAG Conformance Score", metrics.get('WCAG Conformance Score', 0), metrics.get('WCAG Conformance Level', 'N/A')),
                     ("Unique Pages Analyzed", metrics.get('Unique Pages', 0), "Total unique pages scanned"),
                     ("Total Violations Found", metrics.get('Total Violations', 0), "Total instances of accessibility issues"),
                     ("Avg Violations per Page", metrics.get('Average Violations per Page', 0), "Average issues per page"),
                     ("Pages with Critical Issues (%)", metrics.get('Pages with Critical Issues (%)', 0), "% of pages with high-severity barriers"),
                ]
                for name, value, desc in kpi_data:
                     summary_ws.write(current_row, 0, name, metric_name_format)
                     fmt = metric_value_format
                     if "Score" in name:
                         fmt = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter', 'border': 1,
                                                    'bg_color': '#92D050' if value >= 90 else '#FFEB9C' if value >= 75 else '#FFCCCC'})
                     elif name == "Pages with Critical Issues (%)":
                         fmt = percent_format
                         value = value / 100  # <--- AGGIUNGI QUESTO!
                     elif "%" in name: 
                         fmt = percent_format
                     elif isinstance(value, int): 
                         fmt = num_format
                     elif isinstance(value, float): 
                         fmt = num_dec_format
                     else: 
                         fmt = cell_center_format

                     summary_ws.write(current_row, 1, value, fmt)
                     if "Score" in name: # Put level next to score
                          summary_ws.write(current_row, 2, f"Level: {desc}", cell_center_format)
                     else:
                          summary_ws.write(current_row, 2, desc, cell_format)
                     current_row += 1

                current_row += 1 # Add spacer row

                # Impact Distribution Summary
                summary_ws.merge_range(f'A{current_row}:B{current_row}', 'Violation Impact Summary', subtitle_format)
                current_row += 1
                summary_ws.write(current_row, 0, "Impact Level", header_format)
                summary_ws.write(current_row, 1, "Count", header_format)
                summary_ws.write(current_row, 2, "Percentage", header_format)
                current_row += 1
                if 'By Impact' in aggregations and not aggregations['By Impact'].empty:
                     impact_summary_df = aggregations['By Impact']
                     for _, row_data in impact_summary_df.iterrows():
                          impact_level = row_data['impact']
                          fmt = cell_format
                          if impact_level == 'critical': fmt = critical_bg_format
                          elif impact_level == 'serious': fmt = serious_bg_format
                          summary_ws.write(current_row, 0, impact_level.capitalize(), fmt)
                          summary_ws.write(current_row, 1, row_data['Total_Violations'], num_format)
                          summary_ws.write(current_row, 2, row_data['Percentage']/100, percent_format) # Write as fraction for % format
                          current_row += 1
                else:
                     summary_ws.merge_range(f'A{current_row}:C{current_row}', 'No impact data available', cell_center_format)
                     current_row +=1

                # Placeholder for Impact Chart
                chart_start_row = 4 # Align charts roughly with KPIs/Impact
                if 'impact' in chart_files:
                     summary_ws.write(chart_start_row, 2, "Violation Distribution by Impact", header_format)
                     summary_ws.insert_image(chart_start_row + 1, 2, chart_files['impact'], {'x_scale': 0.5, 'y_scale': 0.5})
                     # Adjust current_row if chart placement affects layout significantly
                     current_row = max(current_row, chart_start_row + 15) # Ensure row count progresses past chart


                # Top Recommendations Section
                current_row += 1
                summary_ws.merge_range(f'A{current_row}:C{current_row}', 'Top Priority Issues to Address', subtitle_format)
                current_row += 1
                summary_ws.write(current_row, 0, 'Violation Type', header_format)
                summary_ws.write(current_row, 1, 'Impact', header_format)
                summary_ws.write(current_row, 2, 'Recommendation / WCAG', header_format)
                current_row += 1
                if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
                     # Take top 5-7 based on Priority Score
                     top_issues = aggregations['By Violation'].head(7)
                     for _, issue in top_issues.iterrows():
                          impact = issue.get('Most_Common_Impact', 'unknown')
                          fmt = cell_format
                          if impact == 'critical': fmt = critical_bg_format
                          elif impact == 'serious': fmt = serious_bg_format
                          summary_ws.write(current_row, 0, issue['violation_id'], cell_format)
                          summary_ws.write(current_row, 1, impact.capitalize(), fmt)
                          rec_text = f"{issue.get('Solution_Description', 'Check WCAG')}\n(WCAG: {issue.get('WCAG_Category', 'N/A')} {issue.get('WCAG_Criterion', 'N/A')})"
                          summary_ws.write(current_row, 2, rec_text, cell_format)
                          current_row += 1
                else:
                     summary_ws.merge_range(f'A{current_row}:C{current_row}', 'No violation data for recommendations', cell_center_format)
                     current_row += 1

                 # Placeholder for other key charts (e.g., WCAG Categories)
                if 'wcag_categories' in chart_files:
                     chart2_start_row = current_row + 1
                     summary_ws.write(chart2_start_row, 2, "Violations by WCAG Principle", header_format)
                     summary_ws.insert_image(chart2_start_row + 1, 2, chart_files['wcag_categories'], {'x_scale': 0.5, 'y_scale': 0.5})
                     current_row = max(current_row, chart2_start_row + 15)


                # --- 2. Detailed Analysis Worksheet ---
                detail_ws = workbook.add_worksheet('Detailed Analysis')
                detail_ws.merge_range('A1:G1', 'Detailed Accessibility Aggregations', title_format)
                current_row_detail = 3

                # Write aggregations using the helper function
                if 'By Violation' in aggregations:
                    current_row_detail = write_df_to_excel(detail_ws, aggregations['By Violation'], current_row_detail, "Analysis by Violation Type")
                if 'By Page' in aggregations:
                     current_row_detail = write_df_to_excel(detail_ws, aggregations['By Page'], current_row_detail + 1, "Analysis by Page")
                if 'By Page Type' in aggregations:
                     current_row_detail = write_df_to_excel(detail_ws, aggregations['By Page Type'], current_row_detail + 1, "Analysis by Page Type")
                if 'By Template' in aggregations:
                     current_row_detail = write_df_to_excel(detail_ws, aggregations['By Template'], current_row_detail + 1, "Analysis by Detected Template")


                # --- 3. Template Projection Worksheet (Optional) ---
                if template_projection_df is not None and not template_projection_df.empty:
                    template_ws = workbook.add_worksheet('Template Projection')
                    template_ws.merge_range('A1:I1', 'Template-Based Violation Projection', title_format)
                    # --- Pipeline summary and explanation ---
                    total_templates = template_projection_df['Template'].nunique()
                    total_occurrences = template_projection_df['Occurrence_Count'].sum()
                    analyzed_templates = template_projection_df[template_projection_df['Sample_Violations'] > 0]['Template'].nunique()
                    analyzed_pages = analyzed_templates
                    pipeline_desc = (
                        "In questa sezione viene stimato l'impatto delle violazioni accessibilità proiettando i problemi trovati sulla pagina rappresentativa di ciascun template su tutte le pagine che condividono la stessa struttura. "
                        "\n\nLa pipeline segue questi passi: "
                        "\n- Il crawler identifica e raggruppa tutte le pagine simili (template) e salva la lista completa delle occorrenze. "
                        "\n- Per ogni template viene scelta una pagina rappresentativa che viene analizzata con axe-core. "
                        "\n- Le violazioni trovate su quella pagina vengono moltiplicate per il numero di occorrenze del template, stimando così l'impatto potenziale su tutto il sito. "
                        "\n\nQuesta proiezione aiuta a capire la priorità di intervento anche su pagine non direttamente analizzate."
                    )
                    template_ws.merge_range('A2:I2', pipeline_desc, note_format)
                    # Riepilogo numerico
                    summary_labels = [
                        ("Numero totale di template rilevati", total_templates),
                        ("Numero totale di URL raccolti dal crawler", total_occurrences),
                        ("Numero totale di pagine associate a template", total_occurrences),
                        ("Template effettivamente analizzati (con almeno una pagina rappresentativa)", analyzed_templates),
                        ("Pagine rappresentative analizzate", analyzed_pages)
                    ]
                    row_summary = 3
                    template_ws.write(row_summary, 0, "Riepilogo Pipeline Template Projection:", subtitle_format)
                    for i, (label, value) in enumerate(summary_labels):
                        template_ws.write(row_summary + 1 + i, 0, label, metric_name_format)
                        template_ws.write(row_summary + 1 + i, 1, value, metric_value_format)
                    start_table_row = row_summary + 2 + len(summary_labels)
                    template_ws.merge_range(f'A{start_table_row}:I{start_table_row}', "Risultati dettagliati per ciascun template:", subtitle_format)
                    write_df_to_excel(template_ws, template_projection_df, start_table_row + 1, "Template Projection Results")
                else:
                     self.logger.info("Skipping 'Template Projection' sheet: No projection data provided.")


                # --- 4. Funnel Analysis Worksheet (Optional) ---
                if 'By Funnel' in aggregations and not aggregations['By Funnel'].empty:
                     funnel_ws = workbook.add_worksheet('Funnel Analysis')
                     funnel_ws.merge_range('A1:G1', 'User Journey Funnel Analysis', title_format)
                     funnel_ws.merge_range('A2:G2',
                                            'Analysis of accessibility issues within defined user journeys.',
                                            note_format)
                     current_row_funnel = 4

                     # Funnel Overview Metrics (from main metrics dict)
                     funnel_metrics_summary = metrics.get('Funnel Analysis', {})
                     if funnel_metrics_summary and funnel_metrics_summary.get('Total Funnels Identified', 0) > 0:
                          funnel_ws.merge_range(f'A{current_row_funnel}:G{current_row_funnel}', 'Funnel Overview Metrics', subtitle_format)
                          current_row_funnel += 1
                          funnel_ws.write(current_row_funnel, 0, 'Metric', header_format)
                          funnel_ws.write(current_row_funnel, 1, 'Value', header_format)
                          funnel_ws.write(current_row_funnel, 2, 'Description', header_format)
                          funnel_ws.set_column(0, 0, 30)
                          funnel_ws.set_column(1, 1, 15)
                          funnel_ws.set_column(2, 2, 45)
                          current_row_funnel += 1

                          overview_metrics = [
                              ('Total Funnels Identified', 'Number of unique funnels with issues'),
                              ('Total Pages in Funnels', 'Unique pages part of identified funnels'),
                              ('Total Violations in Funnels', 'Total issues found on funnel pages'),
                              ('Average Violations per Funnel Page', 'Average issues per page within funnels'),
                              ('Critical Funnel Violations', 'High-severity issues within funnels'),
                              ('Serious Funnel Violations', 'Medium-severity issues within funnels'),
                              ('Most Problematic Funnel', 'Funnel with the highest avg severity score'),
                              ('Most Problematic Funnel Score', 'The avg severity score of the top funnel'),
                          ]
                          for name, desc in overview_metrics:
                               value = funnel_metrics_summary.get(name, 'N/A')
                               funnel_ws.write(current_row_funnel, 0, name, metric_name_format)
                               fmt = metric_value_format if isinstance(value, (int, float)) else cell_center_format
                               if "Score" in name and isinstance(value, float): fmt = num_dec_format
                               elif isinstance(value, int): fmt = num_format
                               funnel_ws.write(current_row_funnel, 1, value, fmt)
                               funnel_ws.write(current_row_funnel, 2, desc, cell_format)
                               current_row_funnel += 1
                          current_row_funnel += 1 # Spacer
                     else:
                          funnel_ws.merge_range(f'A{current_row_funnel}:G{current_row_funnel}', 'Funnel Overview Metrics - No Data', subtitle_format)
                          current_row_funnel += 2


                     # Write Funnel Aggregations
                     current_row_funnel = write_df_to_excel(funnel_ws, aggregations['By Funnel'], current_row_funnel, "Analysis by Funnel")
                     if 'By Funnel Step' in aggregations:
                          current_row_funnel = write_df_to_excel(funnel_ws, aggregations['By Funnel Step'], current_row_funnel + 1, "Analysis by Funnel Step")

                     # Embed Funnel Charts
                     funnel_chart_start_row = current_row_funnel + 2
                     funnel_ws.merge_range(f'A{funnel_chart_start_row}:G{funnel_chart_start_row}', 'Funnel Visualizations', subtitle_format)
                     funnel_chart_start_row += 1
                     img_row = funnel_chart_start_row
                     if 'funnel_violations' in chart_files:
                          funnel_ws.insert_image(img_row, 0, chart_files['funnel_violations'], {'x_scale': 0.6, 'y_scale': 0.6})
                          img_row += 20 # Estimate chart height in rows
                     if 'funnel_steps_heatmap' in chart_files:
                           funnel_ws.insert_image(img_row, 0, chart_files['funnel_steps_heatmap'], {'x_scale': 0.6, 'y_scale': 0.6})

                else:
                    self.logger.info("Skipping 'Funnel Analysis' sheet: No funnel data available.")


                # --- 5. Recommendations Worksheet ---
                recom_ws = workbook.add_worksheet('Recommendations')
                recom_ws.merge_range('A1:G1', 'Detailed Recommendations by Violation Type', title_format)
                recom_ws.merge_range('A2:G2', 'Prioritized list of issues with suggested solutions based on analysis.', note_format)
                # Use write_df_to_excel for the recommendation table
                if 'By Violation' in aggregations and not aggregations['By Violation'].empty:
                    # Select relevant columns for recommendations
                    recom_df = aggregations['By Violation'][[
                        'violation_id', 'Most_Common_Impact', 'WCAG_Category', 'WCAG_Criterion',
                        'Total_Occurrences', 'Affected_Pages', 'Priority_Score',
                        'Solution_Description', 'Technical_Solution', 'User_Impact'
                    ]].copy()
                    recom_df.rename(columns={'Most_Common_Impact': 'Impact', 'Total_Occurrences': 'Occurrences'}, inplace=True)
                    # Sort again just to be sure
                    recom_df = recom_df.sort_values('Priority_Score', ascending=False)
                    write_df_to_excel(recom_ws, recom_df, 4, "Violation Recommendations")
                else:
                     recom_ws.merge_range('A4:G4', 'No violation data available for recommendations.', cell_center_format)


                # --- 6. Charts Worksheet ---
                charts_ws = workbook.add_worksheet('Charts')
                charts_ws.merge_range('A1:G1', 'Accessibility Visualizations', title_format)
                charts_ws.merge_range('A2:G2', 'Graphical representation of key findings.', note_format)
                chart_row = 3
                chart_col = 0
                charts_per_row = 2
                chart_descriptions = { # Keep descriptions concise
                    'impact': 'Distribution of violations by severity.',
                    'top_pages': 'Pages with the highest weighted severity score.',
                    'violation_types': 'Most frequent violation types found.',
                    'wcag_categories': 'Violation breakdown by WCAG principle.',
                    'page_type_heatmap': 'Heatmap showing avg. violations per page by type and impact.',
                    'template_analysis': 'Comparison of templates by avg violations and severity.',
                     # Add funnel chart descriptions if needed
                     'funnel_violations': 'Violations distribution across defined user funnels.',
                     'funnel_steps_heatmap': 'Severity hotspots within funnel steps.',
                }

                for i, (name, path) in enumerate(chart_files.items()):
                    # Calculate position
                    current_chart_col_letter = chr(65 + chart_col * 8) # Estimate 8 columns per chart area
                    current_chart_row_num = chart_row + (i // charts_per_row) * 22 # Estimate 22 rows per chart + title

                    title = f'Chart: {name.replace("_", " ").title()}'
                    desc = chart_descriptions.get(name, "")

                    # Merge cells for title and description above the chart
                    charts_ws.merge_range(f'{current_chart_col_letter}{current_chart_row_num}:{chr(ord(current_chart_col_letter)+6)}{current_chart_row_num}', title, subtitle_format)
                    charts_ws.merge_range(f'{current_chart_col_letter}{current_chart_row_num+1}:{chr(ord(current_chart_col_letter)+6)}{current_chart_row_num+1}', desc, note_format)

                    # Insert chart image
                    charts_ws.insert_image(current_chart_row_num + 2, chart_col * 8, path, {'x_scale': 0.7, 'y_scale': 0.7}) # Adjust scale as needed

                    # Move to next column/row
                    chart_col = (chart_col + 1) % charts_per_row


                # --- 7. Raw Data Worksheet ---
                raw_ws = workbook.add_worksheet('Raw Data')
                raw_ws.merge_range('A1:K1', 'Raw Accessibility Violation Data', title_format)
                raw_ws.merge_range('A2:K2', 'Complete dataset of all detected violations. Use filters for detailed exploration.', note_format)
                # Use write_df_to_excel for raw data
                write_df_to_excel(raw_ws, axe_df, 4, "Raw Violation Data")


        except Exception as e:
            self.logger.error(f"Failed to generate Excel report '{output_excel_path}': {e}", exc_info=True)
            # Re-raise the exception so the caller knows report generation failed
            raise RuntimeError(f"Failed to generate Excel report: {e}")

        self.logger.info(f"Report successfully generated: {output_excel_path}")
        return str(output_excel_path)

    def run_analysis(self, input_excel: Optional[str] = None, crawler_state: Optional[str] = None) -> str:
        """
        Run the complete analysis pipeline: Load, Clean, Calculate Metrics,
        Aggregate, Analyze Templates (Projection), Create Charts, Generate Report.
        Uses internal OutputManager for default paths if arguments are None.

        Args:
            input_excel: Path to the input Excel file (ideally _concat). If None, uses default path.
            crawler_state: Optional path to the crawler state .pkl file. If None, uses default path.

        Returns:
            Path to the generated Excel report file.
        """
        self.logger.info(f"--- Starting Accessibility Analysis for domain slug: {self.domain_slug} ---")

        # 1. Load and Clean Data (includes basic funnel ID and optional crawler integration)
        # load_data handles default paths internally if input_excel/crawler_state are None
        df_clean = self.load_data(input_excel=input_excel, crawler_state=crawler_state)
        if df_clean.empty:
             self.logger.error("Analysis aborted: No data loaded or data became empty after cleaning.")
             raise ValueError("No valid data to analyze after loading and cleaning.")

        # 2. Calculate Metrics (includes funnel metrics if applicable)
        metrics = self.calculate_metrics(df_clean)

        # 3. Create Aggregations
        aggregations = self.create_aggregations(df_clean)

        # 4. Template Projection Analysis (Optional, requires PKL)
        template_projection_df = pd.DataFrame() # Default empty
        # Determine the actual crawler state path used (either provided or default)
        actual_crawler_state = crawler_state
        if actual_crawler_state is None and self.output_manager: # If not provided, check default
            crawler_state_path_default = self.output_manager.get_path(
                 "crawler", f"crawler_state_{self.output_manager.domain_slug}.pkl")
            if crawler_state_path_default.exists():
                 actual_crawler_state = str(crawler_state_path_default)

        if actual_crawler_state and Path(actual_crawler_state).exists():
             # Load template structures specifically for projection
             templates_for_proj, _ = self.load_template_data_from_pkl(actual_crawler_state)
             if not templates_for_proj.empty:
                  # Perform projection analysis
                  template_projection_df = self.analyze_templates_projection(templates_for_proj, df_clean)
             else:
                  self.logger.info("Skipping template projection analysis: No valid template structures loaded from PKL.")
        else:
             self.logger.info("Skipping template projection analysis: Crawler state file not provided or not found.")


        # 5. Create Charts (includes funnel charts if applicable)
        chart_files = self.create_charts(metrics, aggregations, df_clean)

        # 6. Generate Report (passing projection results)
        # generate_report handles default output path if needed
        report_path = self.generate_report(
             axe_df=df_clean, # Pass the cleaned data
             metrics=metrics,
             aggregations=aggregations,
             chart_files=chart_files,
             template_projection_df=template_projection_df # Pass projection results
             # output_excel argument is optional in generate_report
        )

        self.logger.info(f"--- Accessibility Analysis Completed Successfully ---")
        return report_path


# --- Main Execution Block ---
def main():
    """
    Main function to run the accessibility analysis tool from command line.
    """
    import argparse

    parser = argparse.ArgumentParser(description='Optimized Accessibility Analysis Tool V2')
    parser.add_argument('--domain', '-d', required=True, help='Domain slug being analyzed (e.g., example_com)')
    parser.add_argument('--input', '-i', help='Path to input Excel file (e.g., accessibility_report_example_com_concat.xlsx). If omitted, uses default path based on domain.')
    parser.add_argument('--crawler', '-c', help='Optional path to crawler state file (.pkl). If omitted, uses default path based on domain.')
    parser.add_argument('--output', '-o', help='Optional path for the final analysis Excel report. If omitted, uses default path.')
    # parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging (DEBUG level)') # Logging level managed by config
    parser.add_argument('--workers', '-w', type=int, help='Number of parallel workers (overrides config)')

    args = parser.parse_args()

    # Basic logger setup before config manager is fully loaded
    logger = logging.getLogger("main_analyzer")
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    try:
        # Initialize configuration and output managers
        # Assume ConfigurationManager can find its config file
        config = ConfigurationManager()
        # Load domain specific config if needed (though not directly used in analyzer currently)
        # domain_config = config.load_domain_config(args.domain)

        # Ensure domain slug is filesystem-safe
        domain_slug = re.sub(r'[^\w\-]+', '_', args.domain.lower())

        output_root = Path(config.get_path("OUTPUT_DIR", "./output")) # Get output dir from config or default
        output_manager = OutputManager(
            base_dir=output_root,
            domain=domain_slug, # Pass the slug directly
            create_dirs=True
        )
        logger.info(f"Output Manager initialized for domain '{domain_slug}'")

        # Create analyzer instance
        analyzer = AccessibilityAnalyzer(
            max_workers=args.workers, # Pass command-line workers if provided
            output_manager=output_manager
        )

        # run_analysis handles default paths using the output_manager
        report_path = analyzer.run_analysis(
            input_excel=args.input,      # Pass None if not provided, load_data will find default
            crawler_state=args.crawler  # Pass None if not provided, load_data will find default
        )

        print(f"\nAnalysis complete. Report saved to: {report_path}")
        return 0

    except FileNotFoundError as e:
        logger.error(f"File Not Found Error: {e}")
        print(f"Error: Required file not found. Details: {e}")
        return 2
    except ValueError as e:
        logger.error(f"Value Error: {e}")
        print(f"Error: Invalid input or configuration. Details: {e}")
        return 3
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        print(f"An unexpected error occurred during analysis. Check logs for details. Error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())