# Authentication configuration
AUTH_CONFIG_SCHEMA = {
    "AUTH_ENABLED": {
        "type": "bool",
        "default": False,
        "description": "Enable authentication support",
    },
    "AUTH_STRATEGY": {
        "type": "str",
        "default": "form",
        "description": "Authentication strategy (form, oauth, etc.)",
        "allowed_values": ["form"]
    },
    "AUTH_LOGIN_URL": {
        "type": "str",
        "default": "",
        "description": "URL of the login page"
    },
    "AUTH_USERNAME": {
        "type": "str",
        "default": "",
        "description": "Username for authentication"
    },
    "AUTH_PASSWORD": {
        "type": "str",
        "default": "",
        "description": "Password for authentication"
    },
    "AUTH_USERNAME_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector for username field"
    },
    "AUTH_PASSWORD_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector for password field"
    },
    "AUTH_SUBMIT_SELECTOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector for submit button"
    },
    "AUTH_SUCCESS_INDICATOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector to verify successful login"
    },
    "AUTH_ERROR_INDICATOR": {
        "type": "str",
        "default": "",
        "description": "CSS selector that indicates login error"
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