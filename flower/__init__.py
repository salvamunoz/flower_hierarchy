VERSION = (2, 2, 0)
# Marks this fork's builds apart from the upstream release they're based on
LOCAL_VERSION = 'hierarchy'
__version__ = '.'.join(map(str, VERSION)) + '+' + LOCAL_VERSION
