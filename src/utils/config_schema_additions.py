# Authentication configuration
AUTH_CONFIG_SCHEMA = {
    "AUTH_ENABLED": {
        "type": "bool",
        "default": False,
        "description": "Enable authentication support",
    },
    "AUTH_STRATEGIES": {
        "type": "list",
        "default": ["form"],
        "description": "Authentication strategies to use (form, http_basic, etc.)",
    },
    "AUTH_FORM_LOGIN_URL": {
        "type": "str",
        "default": "",
        "description": "URL of the form login page",
        "aliases": ["AUTH_LOGIN_URL"]
    },
    "AUTH_FORM_USERNAME": {
        "type": "str",
        "default": "",
        "description": "Username for form authentication",
        "aliases": ["AUTH_USERNAME"]
    },
    "AUTH_FORM_PASSWORD": {
        "type": "str",
        "default": "",
        "description": "Password for form authentication",
        "aliases": ["AUTH_PASSWORD"]
    },
    "AUTH_FORM_USERNAME_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector for username field in form",
        "aliases": ["AUTH_USERNAME_SELECTOR"]
    },
    "AUTH_FORM_PASSWORD_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector for password field in form",
        "aliases": ["AUTH_PASSWORD_SELECTOR"]
    },
    "AUTH_FORM_SUBMIT_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector for submit button in form",
        "aliases": ["AUTH_SUBMIT_SELECTOR"]
    },
    "AUTH_FORM_SUCCESS_INDICATOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector to verify successful login",
        "aliases": ["AUTH_SUCCESS_INDICATOR"]
    },
    "AUTH_FORM_ERROR_INDICATOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector that indicates login error",
        "aliases": ["AUTH_ERROR_INDICATOR"]
    },
    "AUTH_BASIC_USERNAME": {
        "type": "str",
        "default": "",
        "description": "Username for HTTP Basic authentication"
    },
    "AUTH_BASIC_PASSWORD": {
        "type": "str",
        "default": "",
        "description": "Password for HTTP Basic authentication"
    },
    "AUTH_PRE_LOGIN_ACTIONS": {
        "type": "list",
        "default": [],
        "description": "Actions to perform before login"
    },
    "AUTH_POST_LOGIN_ACTIONS": {
        "type": "list",
        "default": [],
        "description": "Actions to perform after login"
    },
    "AUTH_DOMAINS": {
        "type": "dict",
        "default": {},
        "description": "Domain-specific authentication settings"
    },
    "RESTRICTED_AREA_PATTERNS": {
        "type": "list",
        "default": [],
        "description": "URL patterns requiring authentication"
    },
}

# Funnel configuration
FUNNEL_CONFIG_SCHEMA = {
    "FUNNEL_ANALYSIS_ENABLED": {
        "type": "bool",
        "default": False,
        "description": "Enable funnel analysis"
    },
    "FUNNELS": {
        "type": "dict",
        "default": {},
        "description": "Definition of user flow funnels"
    }
}

# Combined schema additions
CONFIG_SCHEMA_ADDITIONS = {**AUTH_CONFIG_SCHEMA, **FUNNEL_CONFIG_SCHEMA}