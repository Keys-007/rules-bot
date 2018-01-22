import configparser
import logging
import os
import re
from uuid import uuid4

from telegram import Bot, InlineQueryResultArticle, InputTextMessageContent, ParseMode
from telegram.error import BadRequest
from telegram.ext import CommandHandler, RegexHandler, Updater
from telegram.utils.helpers import escape_markdown

import const
from components import inlinequeries, taghints
from const import ENCLOSED_REGEX, ENCLOSING_REPLACEMENT_CHARACTER, GITHUB_PATTERN, OFFTOPIC_CHAT_ID, OFFTOPIC_RULES, \
    OFFTOPIC_USERNAME, ONTOPIC_RULES, ONTOPIC_USERNAME, TELEGRAM_SUPERSCRIPT
from search import search
from util import ARROW_CHARACTER, DEFAULT_REPO, GITHUB_URL, get_reply_id, reply_or_edit

if os.environ.get('ROOLSBOT_DEBUG'):
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.DEBUG)
else:
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)

logger = logging.getLogger(__name__)

self_chat_id = '@'  # Updated in main()


def start(bot, update, args=None):
    if args:
        if args[0] == 'inline-help':
            inlinequery_help(bot, update)
    elif update.message.chat.username not in (OFFTOPIC_USERNAME, ONTOPIC_USERNAME):
        update.message.reply_text("Hi. I'm a bot that will announce the rules of the "
                                  "python-telegram-bot groups when you type /rules.")


def inlinequery_help(bot, update):
    chat_id = update.message.chat_id
    char = ENCLOSING_REPLACEMENT_CHARACTER
    text = (f"Use the `{char}`-character in your inline queries and I will replace "
            f"them with a link to the corresponding article from the documentation or wiki.\n\n"
            f"*Example:*\n"
            f"{SELF_CHAT_ID} I 💙 {char}InlineQueries{char}, but you need an {char}InlineQueryHandler{char} for it.\n\n"
            f"*becomes:*\n"
            f"I 💙 [InlineQueries](https://python-telegram-bot.readthedocs.io/en/latest/telegram.html#telegram"
            f".InlineQuery), but you need an [InlineQueryHandler](https://python-telegram-bot.readthedocs.io/en"
            f"/latest/telegram.ext.html#telegram.ext.InlineQueryHandler) for it.\n\n"
            f"Some wiki pages have spaces in them. Please replace such spaces with underscores. "
            f"The bot will automatically change them back desired space.")
    bot.sendMessage(chat_id, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


def forward_faq(bot: Bot, update):
    if update.message.chat.username not in [ONTOPIC_USERNAME, OFFTOPIC_USERNAME]:
        return

    admins = bot.get_chat_administrators(ONTOPIC_USERNAME)

    if update.effective_user.id not in [x.user.id for x in admins]:
        return

    if not update.message:
        return

    reply_to = update.message.reply_to_message
    if not reply_to:
        return

    try:
        update.message.delete()
    except BadRequest:
        pass

    # Forward message to FAQ channel
    reply_to.forward(const.FAQ_CHANNEL_ID, disable_notification=True)


def rules(bot, update):
    """Load and send the appropiate rules based on which group we're in"""
    if update.message.chat.username == ONTOPIC_USERNAME:
        update.message.reply_text(ONTOPIC_RULES, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    elif update.message.chat.username == OFFTOPIC_USERNAME:
        update.message.reply_text(OFFTOPIC_RULES, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        update.message.reply_text("Hmm. You're not in a python-telegram-bot group, "
                                  "and I don't know the rules around here.")


def docs(bot, update, args, chat_data):
    """ Documentation search """
    if len(args) > 0:
        doc = search.docs(' '.join(args))
        if doc:
            text = (f'*{doc.short_name}*\n'
                    f'_python-telegram-bot_ documentation for this {doc.type}:\n'
                    f'[{doc.full_name}]({doc.url})')

            if doc.tg_name:
                text += f'\n\nThe official documentation has more info about [{doc.tg_name}]({doc.tg_url}).'
        else:
            text = "Sorry, your search term didn't match anything, please edit your message to search again."

        reply_or_edit(bot, update, chat_data, text)


def wiki(bot, update, args, chat_data, threshold=80):
    """ Wiki search """
    query = ' '.join(args)
    if search != '':
        best = search.wiki(query, amount=1, threshold=threshold)

        if best:
            text = (f'Github wiki for _python-telegram-bot_\n'
                    f'[{best[0][0]}]({best[0][1]})')
        else:
            text = "Sorry, your search term didn't match anything, please edit your message to search again."

        reply_or_edit(bot, update, chat_data, text)


def off_on_topic(bot, update, groups):
    chat_username = update.message.chat.username
    if chat_username == ONTOPIC_USERNAME and groups[0] == 'off':
        reply = update.message.reply_to_message
        if reply and reply.text:
            issued_reply = get_reply_id(update)

            update.message.reply_text('I moved this discussion to the '
                                      '[off-topic Group](https://telegram.me/pythontelegrambottalk).',
                                      disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN,
                                      reply_to_message_id=issued_reply)

            if reply.from_user.username:
                name = '@' + reply.from_user.username
            else:
                name = reply.from_user.first_name

            replied_message_text = reply.text

            text = (f'{name} _wrote:_\n'
                    f'{replied_message_text}\n\n'
                    f'⬇️ ᴘʟᴇᴀsᴇ ᴄᴏɴᴛɪɴᴜᴇ ʜᴇʀᴇ ⬇️')

            bot.sendMessage(OFFTOPIC_CHAT_ID, text, disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text('The off-topic group is [here](https://telegram.me/pythontelegrambottalk). '
                                      'Come join us!',
                                      disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)

    elif chat_username == OFFTOPIC_USERNAME and groups[0] == 'on':
        update.message.reply_text('The on-topic group is [here](https://telegram.me/pythontelegrambotgroup). '
                                  'Come join us!',
                                  disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)


def sandwich(bot, update, groups):
    if update.message.chat.username == OFFTOPIC_USERNAME:
        if 'sudo' in groups[0]:
            update.message.reply_text("Okay.", quote=True)
        else:
            update.message.reply_text("What? Make it yourself.", quote=True)


def github(bot, update, groupdict):
    # TODO: Handle multiple references in the same message
    user, repo, number, number_type, sha = [groupdict[x] for x in ('user', 'repo', 'number', 'number_type', 'sha')]
    url = GITHUB_URL
    name = ''
    if number:
        if user and repo:
            url += f'{user}/{repo}'
            name += f'{user}/{repo}'
        else:
            url += DEFAULT_REPO
        url += f'/issues/{number}'
        name += f'{number_type}{number}'
    else:
        if user:
            name += user
            if repo:
                url += f'{user}/{repo}'
                name += f'/{repo}'
            name += '@'
        if not repo:
            url += DEFAULT_REPO
        name += sha[:7]
        url += f'/commit/{sha}'
    update.message.reply_text(f'[{name}]({url})', parse_mode=ParseMode.MARKDOWN)


def fuzzy_replacements_markdown(query, threshold=95, official_api_links=True):
    """ Replaces the enclosed characters in the query string with hyperlinks to the documentations """
    symbols = re.findall(ENCLOSED_REGEX, query)

    if not symbols:
        return None, None

    replacements = list()
    for s in symbols:
        # Wiki first, cause with docs you can always prepend telegram. for better precision
        wiki = search.wiki(s.replace('_', ' '), amount=1, threshold=threshold)
        if wiki:
            name = wiki[0][0].split(ARROW_CHARACTER)[-1].strip()
            text = f'[{name}]({wiki[0][1]})'
            replacements.append((wiki[0][0], s, text))
            continue

        doc = search.docs(s, threshold=threshold)
        if doc:
            text = f'[{doc.short_name}]({doc.url})'

            if doc.tg_url and official_api_links:
                text += f' [{TELEGRAM_SUPERSCRIPT}]({doc.tg_url})'

            replacements.append((doc.short_name, s, text))
            continue

        # not found
        replacements.append((s + '❓', s, escape_markdown(s)))

    result = query
    for name, symbol, text in replacements:
        char = ENCLOSING_REPLACEMENT_CHARACTER
        result = result.replace(f'{char}{symbol}{char}', text)

    result_changed = [x[0] for x in replacements]
    return result_changed, result


def article(title='', description='', message_text=''):
    return InlineQueryResultArticle(
        id=uuid4(),
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(
            message_text=message_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True)
    )


def error(bot, update, err):
    """Log all errors"""
    logger.warning(f'Update "{update}" caused error "{err}"')


def main():
    config = configparser.ConfigParser()
    config.read('bot.ini')

    updater = Updater(token=config['KEYS']['bot_api'])
    dispatcher = updater.dispatcher

    global self_chat_id
    self_chat_id = f'@{updater.bot.get_me().username}'

    start_handler = CommandHandler('start', start, pass_args=True)
    rules_handler = CommandHandler('rules', rules)
    rules_handler_hashtag = RegexHandler(r'.*#rules.*', rules)
    docs_handler = CommandHandler('docs', docs, pass_args=True, allow_edited=True, pass_chat_data=True)
    wiki_handler = CommandHandler('wiki', wiki, pass_args=True, allow_edited=True, pass_chat_data=True)
    sandwich_handler = RegexHandler(r'(?i)[\s\S]*?((sudo )?make me a sandwich)[\s\S]*?', sandwich, pass_groups=True)
    off_on_topic_handler = RegexHandler(r'(?i)[\s\S]*?\b(?<!["\\])(off|on)[- _]?topic\b', off_on_topic,
                                        pass_groups=True)
    github_handler = RegexHandler(GITHUB_PATTERN, github, pass_groupdict=True)
    forward_faq_handler = RegexHandler(r'(?i).*#faq.*', forward_faq)

    taghints.register(dispatcher)
    dispatcher.add_handler(forward_faq_handler)
    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(rules_handler)
    dispatcher.add_handler(rules_handler_hashtag)
    dispatcher.add_handler(docs_handler)
    dispatcher.add_handler(wiki_handler)
    dispatcher.add_handler(sandwich_handler)
    dispatcher.add_handler(off_on_topic_handler)
    dispatcher.add_handler(github_handler)

    inlinequeries.register(dispatcher)
    dispatcher.add_error_handler(error)

    updater.start_polling()
    logger.info('Listening...')
    updater.idle()


if __name__ == '__main__':
    main()
