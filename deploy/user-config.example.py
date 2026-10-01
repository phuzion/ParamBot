# Copy to user-config.py in PYWIKIBOT_DIR and fill in the account name.
# Never commit user-config.py or user-password.py.
family = 'wikipedia'
mylang = 'en'
usernames['wikipedia']['en'] = 'ParamBot'

# user-password.py contains one line:
#   ('ParamBot', BotPassword('parambot', '<password from Special:BotPasswords>'))
# Give the bot password the "High-volume (bot) access" grant (the bot refuses
# to run live without the bot right) and "Edit existing pages".
password_file = 'user-password.py'

put_throttle = 10   # seconds between edits
# Edits use Pywikibot's default maxlag of 5. Don't set it here: Pywikibot 11.8
# renamed maxlag to write_maxlag, and each version warns about the other name.
