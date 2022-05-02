#!/usr/bin/python3.10
# -*- coding:utf-8 -*-

#    Memory Hammer, An always on Anki-review system.
#    Copyright (C) 2022  Abishek Muthian (www.memoryhammer.com).
#
#    This program is free software: you can redistribute it and/or #modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public #License
#    along with this program.  If not, see <https://www.gnu.org/#licenses/>.

import sys
import os

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'memory-hammer/images')
fontdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'memory-hammer/fonts')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'memory-hammer/lib')

if os.path.exists(libdir):
    sys.path.append(libdir)

from TP_lib import gt1151
from TP_lib import epd2in13_V2
import time
from PIL import Image, ImageDraw, ImageFont
import logging
import traceback
import threading
import json
import urllib.request
from functools import reduce
import re
import schedule

# Config
IPAddress = '192.168.3.129'
Port = '8775'
logging.basicConfig(level=logging.INFO)
# Do not change this
flag_t = 1


def pthread_irq():
    """
    Thread to read touch signal
    """
    logging.debug("pthread running")
    while flag_t == 1:
        if gt.digital_read(gt.INT) == 0:
            GT_Dev.Touch = 1
        else:
            GT_Dev.Touch = 0
    logging.debug("thread:exit")


def text_wrap(text, font=None, max_width=None):
    """
    Splits a long text to smaller lines which can fit in a line with max_width.
    Uses a Font object for more accurate calculations.
    Part of the text formatting routine from https://simonsomlai.com/en/e-paper-quote-display-raspberry-pi.

    :param text:
    :param font:
    :param max_width:
    :return:
    """
    lines = []
    if font.getsize(text)[0] < max_width:
        logging.debug(f"Appending lines, Font size: {font.getsize(text)[0]}, Max Width: {max_width}")
        lines.append(text)
    else:
        words = text.split(' ')
        i = 0
        while i < len(words):
            line = ''
            while i < len(words) and font.getsize(line + words[i])[0] <= max_width:
                line = line + words[i] + " "
                i += 1
            if not line:
                line = words[i]
                i += 1
            lines.append(line)
    return lines


def slice_index(x):
    """
    Gives the index of the first alphabet.
    :param x:
    :return:
    """
    i = 0
    for c in x:
        if c.isalpha():
            i += 1
            return i
        i += 1


# TODO: Should the case be altered?
def upper_first(x):
    """
    Converts the first alphabet to upper case.
    :param x:
    :return:
    """
    i = slice_index(x)
    return x[:i].upper() + x[i:]


def within_width(textlist, font, screen_width):
    """
    Ensure that the text is within the width of the screen.
    :param textlist:
    :param font:
    :param screen_width:
    :return:
    """
    padding = 10
    for word in textlist:
        logging.debug(f"Size of the word: {font.getsize(word)[0] + padding} and Screen Width: {screen_width}")
        if font.getsize(word)[0] + padding > screen_width:
            return False
    return True


def make_it_pretty(text, spacing, screen_height, screen_width, padding, font_name):
    """
    Calculates font-size, line-wrapping, vertical centering, # of lines, strips not-needed parts AND does your dishes
    Taken from https://simonsomlai.com/en/e-paper-quote-display-raspberry-pi and added some custom hacks.

    :param text:
    :param spacing:
    :param screen_height:
    :param screen_width:
    :param padding:
    :param font_name:
    :return:
    """
    logging.debug("Formatting...")
    font_sizes = [64, 56, 48, 40, 32, 24, 18]
    attempt = 0
    logging.debug("Removing html tags from the text")
    r = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')
    text = re.sub(r, ' ', text)
    while True:
        logging.debug(f"Text: {text}")
        attempt += 1
        logging.debug(f"Text try {attempt}")
        for size in font_sizes:
            font = ImageFont.truetype(os.path.join(fontdir, font_name), size)
            line_height = font.getsize('hg')[1] + spacing
            max_lines = (screen_height // line_height)
            splitted_text = text.split("\n")
            result = [text_wrap(part, font=font, max_width=screen_width - (padding * 2)) for part in splitted_text]
            blocks = reduce(lambda x, y: x + y, result)
            trimmed_blocks = [x.strip() for x in blocks]
            r = re.compile("[\w\"]+")
            filtered_list = list(filter(r.match, trimmed_blocks))
            line_length = len(filtered_list)
            text_height = line_height * line_length
            offset_y = ((screen_height / 2) - (text_height / 2))
            if (line_length <= max_lines) and (text_height + offset_y < screen_height) and within_width(filtered_list,
                                                                                                        font,
                                                                                                        screen_width):
                text = upper_first("\n".join(filtered_list))
                logging.debug(
                    f"{text},\n Font size: {size}, Line count: {line_length}, Quote height: {text_height}, Offset: {offset_y}, Screen height: {screen_height}")
                return {
                    "text": text,
                    "offset": offset_y,
                    "font": font
                }
            elif 7 < attempt < 20:
                logging.debug(f"Lowest font size exceeded, Trimming text: {text}")
                text = text.rsplit(' ', 1)[0] + '...'
            elif attempt > 20:
                logging.error(f"Error rendering the card text")
                text = "Couldn't render card text. Please simplify."


def request(action, **params):
    """
    Prepare request for Anki-Connect

    :param action:
    :param params:
    :return:
    """
    return {'action': action, 'params': params, 'version': 6}


def invoke(action, **params):
    """
    Send request to Anki-Connect

    :param action:
    :param params:
    :return:
    """
    requestJson = json.dumps(request(action, **params)).encode('utf-8')
    response = json.load(urllib.request.urlopen(urllib.request.Request('http://'+IPAddress+':'+Port, requestJson)))
    if len(response) != 2:
        raise Exception('response has an unexpected number of fields')
    if 'error' not in response:
        raise Exception('response is missing required error field')
    if 'result' not in response:
        raise Exception('response is missing required result field')
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']


def show_user_info(operation):
    """
    Handles error and information screen

    :param operation:
    """
    match operation:
        case 'Show Deck':
            text = 'No Anki deck was found.'
        case 'Show Card':
            text = 'No due Anki card was found. Auto re-attempt in 20 minutes.'
        case 'Show Card Info':
            text = 'Error fetching card info.'
        case 'Render Error':
            text = 'Error rendering the card text.'
        case 'default':
            text = 'Unknown issue. Please report.'

    line_spacing = 1
    padding_x = 15
    padding_y = 5

    screen_width = epd.height
    screen_height = epd.width - padding_y
    logging.debug(f"Screen height: {screen_height}, Screen Width: {screen_width}")

    try:
        formatted_result = make_it_pretty(text, line_spacing, screen_height, screen_width, padding_x,
                                          'Roboto-Black.ttf')
    except Exception as e:
        logging.error(f"Could not format the text: {e}")
        show_user_info('Render Error')
        return

    text = formatted_result["text"]
    offset_y = formatted_result["offset"]
    font = formatted_result["font"]

    logging.debug("Updating...")
    DrawImage.text((padding_x, offset_y), text, fill=0, align="left", spacing=line_spacing, font=font)


def get_anki_decks():
    """
    Fetches the decks from Anki
    """
    global decks
    global deck_length

    decks = invoke('deckNames')
    logging.debug(f"Got list of decks: {decks}")
    deck_length = len(decks)


def get_anki_cards():
    """
    Fetches the cards from Anki
    """
    global cards

    logging.debug('Getting Anki Cards')
    query = '"deck:' + decks[deck_position] + '"'
    logging.debug(f"The findCards query is: {query}")
    cards = invoke('findCards', query=query)
    logging.debug(f"Got list of cards: {cards}")
    logging.debug('Checking if the cards are due...')
    due = invoke('areDue', cards=cards)
    logging.debug(f"Got the due: {due}")
    new_cards = []
    for i in range(len(due)):
        if due[i]:
            new_cards.append(cards[i])
    cards = new_cards
    logging.debug('Cards which are due: {}'.format(cards))


def get_anki_card_info(card_ids):
    """
    Fetches the card information from Anki

    :param card_ids:
    """
    global cards

    cards = invoke('cardsInfo', cards=card_ids)

    if len(cards) > 0:
        logging.debug(f"Card Info: {cards}")
        logging.debug(f"Front of the card: {cards[0]['fields']['Front']['value']}")
        logging.debug(f"Back of the card: {cards[0]['fields']['Back']['value']}")
        logging.debug(f"Factor of the card: {cards[0]['factor']}")


def show_anki_deck(font_name, draw):
    """
    Displays the Anki deck to the screen

    :param font_name:
    :param draw:
    """

    logging.debug(f"Length of Decks {deck_length}")
    # Accommodating the text in display
    line_spacing = 1
    padding_x = 15
    padding_y = 5

    screen_width = epd.height
    screen_height = epd.width - padding_y
    logging.debug(f"Screen height {screen_height}, Screen Width: {screen_width}")

    try:
        formatted_result = make_it_pretty(decks[deck_position], line_spacing, screen_height, screen_width, padding_x,
                                          font_name)
    except Exception as e:
        logging.error(f"Could not format the text: {e}")
        show_user_info('Render Error')
        return

    text = formatted_result["text"]
    offset_y = formatted_result["offset"]
    font = formatted_result["font"]

    logging.debug("Updating...")
    draw.text((padding_x, offset_y), text, fill=0, align="left", spacing=line_spacing, font=font)


def show_anki_card(card_position, side, font_name, draw):
    """
    Displays the Anki card to the screen

    :param card_position:
    :param side:
    :param font_name:
    :param draw:
    """
    # For rotation, I'm using height instead of width and vice-versa
    line_spacing = 1
    padding_x = 15
    padding_y = 5

    screen_width = epd.height
    screen_height = epd.width - padding_y

    try:
        formatted_result = make_it_pretty(cards[card_position]['fields'][side]['value'], line_spacing, screen_height,
                                          screen_width, padding_x, font_name)
    except Exception as e:
        logging.error(f"Could not format the text: {e}")
        show_user_info('Render Error')
        return

    text = formatted_result["text"]
    offset_y = formatted_result["offset"]
    font = formatted_result["font"]

    logging.debug("Updating...")
    draw.text((padding_x, offset_y), text, fill=0, align="left", spacing=line_spacing, font=font)


def run_continuously(interval=1):
    """Continuously run, while executing pending jobs at each
    elapsed time interval.
    @return cease_continuous_run: threading. Event which can
    be set to cease continuous run. Please note that it is
    *intended behavior that run_continuously() does not run
    missed jobs*. For example, if you've registered a job that
    should run every minute and you set a continuous run
    interval of one hour then your job won't be run 60 times
    at each interval but only once.
    """
    cease_continuous_run = threading.Event()

    class ScheduleThread(threading.Thread):
        @classmethod
        def run(cls):
            while not cease_continuous_run.is_set():
                schedule.run_pending()
                time.sleep(interval)

    continuous_thread = ScheduleThread()
    continuous_thread.start()
    return cease_continuous_run


def schedule_anki_card_fetch():
    """
    Fetches the anki cards automatically and displays the first card if available
    :return:
    """
    global re_flag
    global page
    global stop_run_continuously

    logging.debug("Running scheduled Anki card fetch")
    get_anki_cards()
    if len(cards) > 0:
        logging.debug(f"Cancelling the scheduled jobs")
        # Stop the background thread
        stop_run_continuously.set()
        get_anki_card_info(cards)
        if len(cards) > 0:
            try:
                page = 3
                read_bmp(PagePath[page], 0, 0)
                show_anki_card(card_position, 'Front', 'Roboto-Black.ttf', DrawImage)
            except Exception as e:
                logging.error(f"Error showing the selected card: {e}")
                page = 1
                read_bmp(PagePath[page], 0, 0)
                show_user_info('Show Card Info')
        re_flag = 1


def read_bmp(file, x, y):
    """
    Loads the images to be displayed on the screen

    :param file:
    :param x:
    :param y:
    """
    new_image = Image.open(os.path.join(picdir, file))
    image.paste(new_image, (x, y))


def select_card_to_show():
    """
    Selects a card to display if available
    """
    global page

    if len(cards) > 0:
        try:
            read_bmp(PagePath[page], 0, 0)
            show_anki_card(card_position, 'Front', 'Roboto-Black.ttf', DrawImage)
        except Exception as e:
            logging.error(f"Error showing the selected card: {e}")
            page = 1
            read_bmp(PagePath[page], 0, 0)
            show_user_info('Show Card Info')
    else:
        page = 1
        read_bmp(PagePath[page], 0, 0)
        show_user_info('Show Card')
        logging.debug(f"Would retry fetching card info in 20 minutes")
        schedule.every(20).minutes.do(schedule_anki_card_fetch)

        # Start the background thread
        global stop_run_continuously
        stop_run_continuously = run_continuously()


def set_ease_factor(category, card):
    """
    Sets the Ease Factor for the Anki card during review

    :param category:
    :param card:
    """
    ease_factor = card['factor']
    if ease_factor == 0:
        ease_factor = 2500

    match category:
        case 'Again':
            ease_factor -= 200
        case 'Hard':
            ease_factor -= 150
        case 'Good':
            ease_factor = ease_factor
        case 'Easy':
            ease_factor += 150

    invoke('setEaseFactors', cards=[card['cardId']], easeFactors=[ease_factor])
    logging.debug("Ease Factor set")


try:
    logging.info("Memory Hammer")

    epd = epd2in13_V2.EPD_2IN13_V2()
    gt = gt1151.GT1151()
    GT_Dev = gt1151.GT_Development()
    GT_Old = gt1151.GT_Development()

    logging.debug("init and Clear")
    epd.init(epd.FULL_UPDATE)
    gt.GT_Init()
    epd.Clear(0xFF)

    t = threading.Thread(target=pthread_irq, daemon=True)
    t.start()

    image = Image.open(os.path.join(picdir, 'Menu.bmp'))
    epd.displayPartBaseImage(epd.getbuffer(image))
    DrawImage = ImageDraw.Draw(image)
    epd.init(epd.PART_UPDATE)

    i = j = k = re_flag = self_flag = page = deck_length = deck_position = card_position = 0

    PagePath = ["Menu.bmp", "Info.bmp", "Photo_1.bmp", "Photo_2.bmp", "Photo_3.bmp"]
    decks = []
    cards = []
    stop_run_continuously = None

    while True:
        if i > 12 or re_flag == 1:
            if page == 1 and self_flag == 0:
                epd.displayPartial(epd.getbuffer(image))
            else:
                epd.displayPartial_Wait(epd.getbuffer(image))
            i = 0
            k = 0
            j += 1
            re_flag = 0
            logging.debug("*** Draw Refresh ***")
        elif k > 50000 and i > 0 and page == 1:
            epd.displayPartial(epd.getbuffer(image))
            i = 0
            k = 0
            j += 1
            logging.debug("*** Overtime Refresh ***")
        elif j > 50 or self_flag:
            self_flag = 0
            j = 0
            epd.init(epd.FULL_UPDATE)
            epd.displayPartBaseImage(epd.getbuffer(image))
            epd.init(epd.PART_UPDATE)
            logging.debug("--- Self Refresh ---")
        else:
            k += 1
        # Read the touch input
        gt.GT_Scan(GT_Dev, GT_Old)
        if GT_Old.X[0] == GT_Dev.X[0] and GT_Old.Y[0] == GT_Dev.Y[0] and GT_Old.S[0] == GT_Dev.S[0]:
            continue

        if GT_Dev.TouchpointFlag:
            i += 1
            GT_Dev.TouchpointFlag = 0

            if page == 0 and re_flag == 0:  # Main Menu
                if 40 < GT_Dev.X[0] < 80 and 70 < GT_Dev.Y[0] < 175:
                    logging.debug("Get Decks ...")
                    page = 2
                    get_anki_decks()
                    read_bmp(PagePath[page], 0, 0)
                    show_anki_deck('Roboto-Black.ttf', DrawImage)
                    re_flag = 1

            if page == 1 and re_flag == 0:  # Info

                if 0 < GT_Dev.X[0] < 25 and 115 < GT_Dev.Y[0] < 136:
                    logging.debug("Home ...")
                    if not stop_run_continuously.is_set():
                        logging.debug(f"Cancelling the scheduled jobs")
                        # Stop the background thread
                        stop_run_continuously.set()

                    page = 0
                    read_bmp(PagePath[page], 0, 0)
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 0 < GT_Dev.Y[0] < 40:
                    logging.debug("Refresh ...")
                    self_flag = 1
                    re_flag = 1

            if page == 2 and re_flag == 0:  # Show Deck
                if 0 < GT_Dev.X[0] < 25 and 115 < GT_Dev.Y[0] < 136:
                    logging.debug("Home ...")
                    page = 0
                    deck_position = 0
                    read_bmp(PagePath[page], 0, 0)
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 165 < GT_Dev.Y[0] < 200:
                    logging.debug("Next page ...")
                    deck_position += 1
                    if deck_position == deck_length:  # Reached the end of deck
                        deck_position = 0
                    re_flag = 2
                elif 0 < GT_Dev.X[0] < 25 and 55 < GT_Dev.Y[0] < 90:
                    logging.debug("Last page ...")
                    if deck_position == 0:
                        logging.debug("Top page ...")
                    else:
                        deck_position -= 1
                        re_flag = 2
                elif 0 < GT_Dev.X[0] < 25 and 0 < GT_Dev.Y[0] < 40:
                    logging.debug("Refresh ...")
                    self_flag = 1
                    re_flag = 1
                elif 25 < GT_Dev.X[0] < 122 and 0 < GT_Dev.Y[0] < 250 and re_flag == 0:
                    logging.debug("Select deck ...")
                    page = 3
                    get_anki_cards()
                    if len(cards) > 0:
                        get_anki_card_info(cards)
                    select_card_to_show()
                    re_flag = 1
                if re_flag == 2:  # Refresh small photo
                    re_flag = 1
                    read_bmp(PagePath[page], 0, 0)
                    show_anki_deck('Roboto-Black.ttf', DrawImage)

            if page == 3 and re_flag == 0:  # view the card
                if 0 < GT_Dev.X[0] < 25 and 55 < GT_Dev.Y[0] < 185:
                    logging.debug("Show Answer ...")
                    page = 4
                    read_bmp(PagePath[page], 0, 0)
                    show_anki_card(card_position, 'Back', 'Roboto-Black.ttf', DrawImage)
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 210 < GT_Dev.Y[0] < 240:
                    logging.debug("Home ...")
                    page = 0
                    read_bmp(PagePath[page], 0, 0)
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 0 < GT_Dev.Y[0] < 40:
                    logging.debug("Refresh ...")
                    self_flag = 1
                    re_flag = 1

            if page == 4 and re_flag == 0:  # review the card
                if 0 < GT_Dev.X[0] < 25 and 50 < GT_Dev.Y[0] < 70:
                    logging.debug("Again ...")
                    set_ease_factor('Again', cards[0])
                    cards.pop(0)
                    page = 3
                    select_card_to_show()
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 90 < GT_Dev.Y[0] < 115:
                    logging.debug("Hard ...")
                    set_ease_factor('Hard', cards[0])
                    cards.pop(0)
                    page = 3
                    select_card_to_show()
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 130 < GT_Dev.Y[0] < 160:
                    logging.debug("Good ...")
                    set_ease_factor('Good', cards[0])
                    cards.pop(0)
                    page = 3
                    select_card_to_show()
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 180 < GT_Dev.Y[0] < 200:
                    logging.debug("Easy ...")
                    set_ease_factor('Easy', cards[0])
                    cards.pop(0)
                    page = 3
                    select_card_to_show()
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 225 < GT_Dev.Y[0] < 240:
                    logging.debug("Home ...")
                    page = 0
                    read_bmp(PagePath[page], 0, 0)
                    re_flag = 1
                elif 0 < GT_Dev.X[0] < 25 and 0 < GT_Dev.Y[0] < 40:
                    logging.debug("Refresh ...")
                    self_flag = 1
                    re_flag = 1

except IOError as e:
    logging.debug(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")

    if stop_run_continuously:
        if not stop_run_continuously.is_set():
            stop_run_continuously.set()
            logging.info(f"Cancelling the scheduled jobs")
    flag_t = 0
    epd.sleep()
    time.sleep(2)
    t.join()
    epd.Dev_exit()
    exit()
