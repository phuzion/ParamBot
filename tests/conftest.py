import os

# Before anything imports Pywikibot: the tests never touch a wiki, so they
# need no user-config.py.
os.environ.setdefault('PYWIKIBOT_NO_USER_CONFIG', '2')
