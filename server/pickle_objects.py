import random

num_players = 2

class clientGame:
    def __init__(self, game_stage, clockwise, playDeck, len_gameDeck, len_discardDeck):
        self.player = None
        self.opp_list = []
        self.turn = None
        self.clockwise = clockwise
        self.playDeck = playDeck
        self.len_gameDeck = len_gameDeck
        self.len_discardDeck = len_discardDeck
        self.game_stage = game_stage
        self.info = ''
        """detail_cards refer to attempted cards that were played, last_cards, etc."""
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
        """
        data.actions
        0 : not players turn - Type : T/F
        1 : players turn, can play from hand - type : list of indeces
        2 : players turn, can play from topcards - type : list of indeces
        3 : player cannot play, pick up (y/n) - Type : T/F
        4 : player cannot play, cannot pick up: eats - Type : T/F
        5 : player - attempt to play from bottomcards - Type : T/F
        """


class clientOpponent():
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

class Card:
    """has attributes suit referring to diamonds, hearts etc and val referring to A, K, 2 etc (2-->14)"""
    def __init__(self, suit, val):
        self.suit = suit
        self.val = val
        self.image = None
        self.client_update = False

class Deck(list):
    """list which will be composed of objects of type Card"""
    def __init__(self):
        self.client_update = False
        pass

    def build(self):
        """52 cards (type Card) (4 suits of 13 cards each) are added to deck (self)"""
        for suit in ["Hearts", "Diamonds", "Clubs", "Spades"]:
            for val in range(2, 15):
                self.append(Card(suit, val))

    def shuffle(self):
        """shuffles card by removing random card from self and adding to another deck until self has length 0"""
        temp = []
        while len(self) > 0:
            r = random.randint(0, len(self) - 1)
            temp.append(self.pop(r))
        self.extend(temp)

    def drawCard(self):
        """returns and removes last card in self"""
        return self.pop()

    def drawRandom(self):
        i = random.randint(0, len(self) - 1)
        return self.pop(i)

class Player():

    """each player in the game has following attributes"""
    def __init__(self, client, name):
        self.done = False
        self.turn = False
        self.eat = False
        self.client = client
        self.clockwise = True
        self.client_data = None
        self.actions = [True, False, False, False, False] # copy from clientPlayer()
        self.detail_cards = []
        self.name = name
        self.hand = Deck()
        self.bottom_cards = [Deck(), Deck(), Deck()]
        self.top_cards = [Deck(), Deck(), Deck()]

        self.info_dump = []
        self.gamestart = False

    def dealCards(self, deck):
        """adds 3 cards to players' 3 decks each and removes from gameDeck"""
        for i in range(3):
            self.bottom_cards[i].append(deck.drawCard())
            self.hand.append(deck.drawCard())
            self.top_cards[i].append(deck.drawCard())

    def play(self, deck, play_list):
        """takes list of indexes of cards to be played from a deck as parameter
        and returns list with cards in order that they were played"""
        temp = []
        for i in play_list:
            temp.append(deck[i])
        for index in sorted(play_list, reverse=True):
            del deck[index]
        return temp