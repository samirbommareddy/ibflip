import pygame

pygame.init()

WIDTH = 1280
HEIGHT = 720

MARGIN = 40
SCREEN_CARD_RATIO = 6
card_height = (HEIGHT - (2 * MARGIN)) // SCREEN_CARD_RATIO
card_width = int(0.6887 * card_height) # ratio of png files
hand_height = HEIGHT - card_height - MARGIN
card_space = card_height // 7
hand_fixed_space = WIDTH // 7
hand_left_edge = MARGIN + (3 * (card_space + card_width)) + hand_fixed_space
hand_width = WIDTH - hand_left_edge - MARGIN
playDeck_topleft = (WIDTH//2 - card_width//2, HEIGHT//2 - card_height//2)

suit_dict = {"Hearts" : "hearts", "Diamonds" : "diamonds", "Clubs" : "clubs", "Spades" : "spades"}
val_dict = {1 : '1', 2 : '2', 3 : '3', 4 : '4', 5 : '5', 6 : '6', 7 : '7', 8 : '8', 9 : '9', 10 : '10', 11 : 'jack', 12 : 'queen', 13 : 'king', 14: 'ace'}
cards_pos = {}


class clientGame:
    """stores attributes for a given moment in the game"""
    def __init__(self, game_stage, turn, clockwise, playDeck, len_gameDeck, len_discardDeck):
        self.player = None
        self.opp_list = []
        self.turn = turn # may not need this
        self.clockwise = clockwise
        self.playDeck = playDeck
        self.len_gameDeck = len_gameDeck
        self.len_discardDeck = len_discardDeck
        self.game_stage = game_stage
        self.info = ''
        self.detail_cards = []


class clientPlayer():
    """client is player in the game and has following attributes"""
    def __init__(self):
        self.hand = []
        self.top_cards = [None, None, None]
        self.is_bottom_cards = [True, True, True]
        self.bottom_cards = [None, None, None]
        self.actions = [True, False, False, False, False]
        self.tried_to_play = False
        self.eat = False
        self.win = False
        self.lost = False

        # Indeces for self.actions
        # 0 : not players turn - Type : T/F
        # 1 : players turn, can play from hand - type : list of indeces
        # 2 : players turn, can play from topcards - type : list of indeces
        # 3 : player cannot play, pick up (y/n) - Type : T/F
        # 4 : player cannot play, cannot pick up: eats - Type : T/F
        # 5 : player - attempt to play from bottomcards - Type : T/F


class clientOpponent():
    """stores attributes for each opponent"""
    def __init__(self, name, len_hand):
        """
        len_hand -> int
        top_cards -> list of len 3, elements are lists containing type Card
        bottom_cards -> list of len 3, if empty: False, if hasCard: True
        """
        self.name = name
        self.len_hand = len_hand
        self.top_cards = [[], [], []]
        self.bottom_cards = [True, True, True]
        self.tried_to_play = False
        self.turn = False
        self.eat = False
    
    def highlightRect(self, opp_lstart, opp_space, opp_width):
        """highlights player by creating a rect around player"""
        self.highlight = pygame.rect.Rect(opp_lstart - opp_space//2, MARGIN//2, opp_width + opp_space, MARGIN + 3*card_height//2)


class Card:
    """object for each of the 52 cards in a deck. Stores information around pygame objects, suit, and val"""
    def __init__(self, suit, val):
        #both suit and val should have type string. Val should be '1', 'king', 'ace' etc
        self.suit = suit
        self.val = val
        self.image = pygame.image.load('assets/' + val_dict.get(self.val) + '_of_' + suit_dict.get(self.suit) + '.png').convert_alpha()
        self.rect = self.image.get_rect()
        self.surface = pygame.transform.scale(self.image, (card_width, card_height))

    def update(self):
        """updates card with image path and pygame objects if not already updated"""
        if self.client_update == False:
            self.image = pygame.image.load('assets/' + val_dict.get(self.val) + '_of_' + suit_dict.get(self.suit) + '.png').convert_alpha()
            self.rect = self.image.get_rect()
            """proportionally transform card width and height"""
            """image resolution: 500x726""" #use this to transform instead of calling get_rect()
            card_width = int(card_height * (self.rect.width / self.rect.height))
            self.surface = pygame.transform.scale(self.image, (card_width, card_height))
            self.rect = self.surface.get_rect()
            self.rect.topleft = cards_pos[self.suit, self.val][0]
            self.client_update = True


class HiddenCards:
    """Used to show cards that are not visible to player."""
    def __init__(self, len):
        #len refers to number of cards in deck if deck. If single card, pass 1
        self.len = len
        self.image = pygame.image.load('assets/0_backofcard.png').convert_alpha()
        self.rect = self.image.get_rect()
        self.surface = pygame.transform.scale(self.image, (card_width, card_height))
        self.client_update = False


class Deck(list):
    """list which will be composed of objects of type Card"""
    def __init__(self):
        pass


def initCardDict():
    """creates a dictionary that stores values of all cards and if it is being dragged or not"""
    #initially this is 2*WIDTH, 0
    global cards_pos
    for suit in ["Hearts", "Diamonds", "Clubs", "Spades"]:
        for val in range(2, 15):
            cards_pos[(suit, val)] = [(2*WIDTH, 0), False]

def cardsUpdate(data):
    """updates card images and pygame objects"""
    for cards in data.player.top_cards:
        for card in cards:
            card.update()
    for card in data.player.hand:
        card.update()
    for card in data.playDeck:
        card.update()
