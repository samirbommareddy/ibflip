import random
import time
from pickle_objects import *

# setup players
player_list = []

# setup decks
"""gameDeck is the main deck that one DRAWS FROM, playDeck one PLAYS ON, discardDeck one DISCARDS TO"""
gameDeck = Deck()
playDeck = Deck()
discardDeck = Deck()

# setup gameDeck
gameDeck.build()
gameDeck.shuffle()

win_order = []
lose_order = []

# GAME CONDITIONS AND VARAIBLES
clockwise = True
attack = False
gameOver = False
newRound = True
skip = 0
turn_player = None
gameStart = False
turn = 0
rule_card_val = None

play_list = [] # list with indeces of card played each turn
turn_list = []

#DEFINE IN LOOP
last_cards = []

# --------------------------------------------------------------------------------------------------------------------------------------------
#HELPER FUNCTIONS

def sortDeck(deck):
    """sorts a deck of type list with card types and returns deck"""
    lowest_val_order = [2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14]
    lowest_suit_order = ["Hearts", "Diamonds", "Clubs", "Spades"]
    temp = []
    
    for val in lowest_val_order:
        for suit in lowest_suit_order:
            for card in deck:
                if card.val == val and card.suit == suit:
                    temp.append(deck.pop(deck.index(card)))
    return temp


def player_lowestCard(player_list):
    """returns player in player_list with lowest card and index of lowest card in player's hand"""
    lowest_val_order = [3, 6, 8, 9, 11, 12, 13, 14, 7, 2, 10, 4, 5]
    lowest_suit_order = ["Hearts", "Diamonds", "Clubs", "Spades"]

    lowest_val = 5
    lowest_suit = "Spades"
    lowest_player = None

    for player in player_list:
        for card in player.hand:
            if lowest_val_order.index(card.val) < lowest_val_order.index(lowest_val):
                lowest_val = card.val
                lowest_suit = card.suit
                lowest_player = player
            elif lowest_val_order.index(card.val) == lowest_val_order.index(lowest_val):
                if lowest_suit_order.index(card.suit) < lowest_suit_order.index(lowest_suit):
                    lowest_val = card.val
                    lowest_suit = card.suit
                    lowest_player = player
    
    #turn = player_list.index(lowest_player)
    for card in lowest_player.hand:
        if card.suit == lowest_suit and card.val == lowest_val:
            index_of_card = lowest_player.hand.index(card)
    
    return lowest_player, index_of_card


def cheatDeck(suit, val, give_deck, take_deck):
    """for a given card, the function takes that card away from take_deck and adds it to give_deck"""
    for i in range(len(take_deck)):
        card = take_deck[i]
        if card.suit == suit and card.val == int(val):
            give_deck.append(take_deck[i])
            break

def playableCards(rule_card_val, attack):
    """returns list with vals of cards that are playable on current rules"""
    playable_cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
    
    if rule_card_val == 2:
        pass

    elif rule_card_val == 3:
        pass
        
    elif rule_card_val == 4:
        playable_cards = [4, 5, 6]

    elif rule_card_val == 5:
        pass

    elif rule_card_val == 6:
        if attack == True:
            playable_cards = [4, 5, 6]
        else:
            [2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]

    elif rule_card_val == 7:
        playable_cards = [2, 3, 4, 5, 6, 7, 14]

    elif rule_card_val == 8:
        playable_cards = [2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14]

    elif rule_card_val == 9:
        playable_cards = [2, 4, 5, 7, 9, 10, 11, 12, 13, 14]

    elif rule_card_val == 10:
        pass # new turn

    elif rule_card_val == 11:
        playable_cards = [2, 4, 5, 7, 10, 11, 12, 13, 14]

    elif rule_card_val == 12:
        playable_cards = [2, 4, 5, 7, 10, 12, 13, 14]

    elif rule_card_val == 13:
        playable_cards = [2, 4, 5, 7, 10, 13, 14]  

    elif rule_card_val == 14:
        playable_cards = [2, 4, 5, 7, 10, 14]

    return playable_cards

def nextTurn(current_turn, skip, clockwise, player_list):
    """takes relevant turn parameters and returns index of player in player_list whose turn is next."""
    if clockwise == True:
        nextTurn = ((current_turn + skip + 1) % len(player_list))
    if clockwise == False:
        nextTurn = (current_turn - skip - 1) % len(player_list)
    return nextTurn

def nextRules():
    """changes global variables to adhere to rules for next turn"""
    global turn, playDeck, discardDeck, play_list, clockwise, player_list, attack, rule_card_val, newRound
# establishes play parameters based on card(s) that were played and previous parameters

    turn_over = False
    try: rule_card_val = playDeck[-1].val
    except: pass
    skip = 0 # for use with 8s


    while turn_over == False:

        if rule_card_val == 2:
            turn = turn
            turn_over = True

        elif rule_card_val == 3:
            if len(play_list) % 2 == 1: #isprime
                clockwise = not clockwise
            turn_over = True
            
        elif rule_card_val == 4:
            attack = True
            turn_over = True

        elif rule_card_val == 5:
            i = 1
            while rule_card_val == 5: # if starting card is 5 then rules apply for 5
                if i == len(playDeck):
                    turn_over = True
                    break
                rule_card_val = playDeck[-i].val
                i += 1

        elif rule_card_val == 6:
            turn_over = True

        elif rule_card_val == 7:
            turn_over = True

        elif rule_card_val == 8:
            skip = len(play_list) # play list will only be 8s
            turn_over = True

        elif rule_card_val == 9:
            if not discardDeck: # empty
                turn_over = True
            else:
                drawn_card = discardDeck.drawRandom()
                rule_card_val = drawn_card.val
                playDeck.extend([drawn_card])

        elif rule_card_val == 10:
            discardDeck.extend(playDeck)
            playDeck.clear()
            turn_over = True
            newRound = True

        elif rule_card_val == 11:
            turn_over = True

        elif rule_card_val == 12:
            turn_over = True

        elif rule_card_val == 13:
            turn_over = True  

        elif rule_card_val == 14:
            turn_over = True
        else:
            """to avoid errors - when playdeck empty (anything can play on a 3)"""
            rule_card_val = 3
    
    if rule_card_val not in [2, 10]:
        turn = nextTurn(turn, skip, clockwise, player_list)


def oppList(player):
    """returns list with opponents for player"""
    global player_list
    temp = list(player_list)
    temp.remove(player)
    return temp


def opp_done(player, player_list):
    """checks if attribute done for all players other thatn parameter player is True or False. Returns True if all are True. Else False"""
    check_list = [] 
    temp = list(player_list) # change to opp function
    temp.remove(player)
    for opp in temp:
        if opp.done == True: check_list.append(True)
        else: check_list.append(False)
    if all(check_list) == True: return True
    else: return False
        
def waiting(TIME, player, player_list):
    """runs while loop until opp_done returns true"""
    # repeated inside while loop to avoid any errors
    player.done = True
    wait = False
    while opp_done(player, player_list) == False or wait == False:
        time.sleep(TIME/3)
        wait = opp_done(player, player_list)
        time.sleep(TIME/3)
    time.sleep(TIME)
    player.done = False

def gameReady(player_list):
    """if all players in player_list are ready, returns ready"""
    temp = []
    for player in player_list:
        if player.gamestart == True: temp.append(True)
        else: temp.append(False)
    return all(temp)


# --------------------------------------------------------------------------------------------------------------------------------------------
#GAMEPLAY FUNCTIONS

def fixHand(player, client_data):
    """uses client_data to make changes to players hand and top cards"""
    index_hand, index_top, switch_decision, _ = client_data

    if switch_decision == 's':
        player.hand.insert(index_hand, player.top_cards[index_top].pop(0))
        player.top_cards[index_top].append(player.hand.pop(index_hand + 1))

    elif switch_decision == 'd':
        player.top_cards[index_top].append(player.hand.pop(index_hand))
        player.hand.append(gameDeck.pop())


def gamestart_lowestcard():
    """plays lowestcard of all players"""
    global player_list
    lowest_player, card_index = player_lowestCard(player_list)
    lowest_player.turn = True
    start_card = lowest_player.hand.pop(card_index)
    playDeck.append(start_card)
    lowest_player.hand.append(gameDeck.pop())



def playHand(player):
    """plays cards from players hand and returns play_list"""
    global play_list, playDeck, newRound
    while True:
        time.sleep(0.1)
        if player.client_data != '____NODATA' and type(player.client_data) == list and len(player.client_data) == 2:
            play_list = player.client_data[0]
            break
    playDeck.extend((player.play(player.hand, play_list)))
    newRound = False

def drawNotPlayableHand(player):
    """asks player to draw card if cannot play and returns newRound and playable_index"""
    global player_list, newRound, gameDeck, playable_cards, playable_index, play_list
    player.actions[3] = True
    while True:
        time.sleep(0.1)
        if player.client_data != '____NODATA' and type(player.client_data) == list and len(player.client_data) == 2:
            if player.client_data[0] in ['y', 'n']:
                decision = player.client_data[0]
                break

    player.actions[3] = False
    player.client_data = ['____NODATA', False]

    if decision == 'y':
        drawn_card = gameDeck.drawCard()
        for game_player in player_list: game_player.detail_cards = [drawn_card]
        player.hand.append(drawn_card)

        if player.hand[-1].val in playable_cards:
            play_list = [player.hand.index(player.hand[-1])]
            playDeck.extend((player.play(player.hand, play_list)))
            newRound = False
        else:
            newRound = True
    elif decision == 'n':
        newRound = True
    

def eat(player):
    """cannot play and there are no more cards"""
    global turn, clockwise, playDeck, newRound
    player.eat = True
    turn = nextTurn(turn, 0, clockwise, player_list)
    player.hand.extend(playDeck)
    playDeck.clear()
    newRound = True

def middleGame(player):
    """makes changes to players decks depending on choices made"""
    global play_list, playable_index, playable_cards, playDeck, newRound

    #playable
    for i in range(3):
        if player.top_cards[i]:
            if player.top_cards[i][0].val in playable_cards:
                playable_index.append(i)

    if not playable_index:
        """player cannot play and cannot draw from gamedeck"""
        player.actions[4] = True
        eat(turn_player)

    elif playable_index:
        """can play"""
        player.actions[2] = playable_index
        newRound = False 

    while True:
        time.sleep(0.1)
        if player.client_data != '____NODATA' and type(player.client_data) == list and len(player.client_data) == 2:
            play_list = player.client_data[0]
            break

    x = play_list[0]
    play_list.clear()
    playDeck.extend(player.top_cards[x])
    for card in player.top_cards[x]:
        # only for counting number of cards - required for 3 and 8
        play_list.append(1)
    player.top_cards[x].clear()


def endGame(player):
    """plays bottom card for player and returns none"""
    global playDeck, player_list, play_list, playable_cards, newRound

    r = 0 # card that will be played from bottom cards
    # bottom cards will play in order (left to right)
    while not player.bottom_cards[r]:
        r += 1

    for game_player in player_list: game_player.detail_cards = [player.bottom_cards[r][0]]

    if player.bottom_cards[r][0].val not in playable_cards:
        # need to show the card somehow to all players
        eat(player)
        newRound = True

    elif player.bottom_cards[r][0].val in playable_cards:
        playDeck.extend((player.play(player.bottom_cards[r], [0])))
        play_list.append(1) # only for counting number of cards played, 1 is meaningless here
        newRound = False


def flipping(player):
    """tests if cards have been flipped and returns turn, clockwise, newRound, rule_card_val"""
    global playDeck, discardDeck, player_list, lose_order
    global turn, clockwise, newRound, rule_card_val # these variables are changed if flipped conditions are true

    # flipping
    if len(playDeck) >= 4:

        temp1 = []

        for i in range(1,4 ):
            if playDeck[-i].val == playDeck[-(i+1)].val: temp1.append(True)
            else: temp1.append(False)

        if all(temp1):
            val = playDeck[-i].val
            discardDeck.extend(playDeck)
            playDeck.clear()
            newRound = True

            if val == 3:
                turn = turn
                available_cards = []
                for card in discardDeck:
                    if card.val == 3:
                        available_cards.append(card)
                if len(available_cards) >= len(player_list) - 1:
                    for opp in oppList(player):
                        cheatDeck(available_cards[0].suit, available_cards[0].val, opp.hand, discardDeck)


            elif val == 4:
                turn = nextTurn(turn, 0, clockwise, player_list)
                for card in discardDeck:
                    if card.val == 3:
                        cheatDeck(card.suit, card.val, player.hand, discardDeck)
                        break # only give one 3

            elif val == 8:
                turn = nextTurn(turn, 0, clockwise, player_list)
                lose_order.append(player)
                player_list.remove(player)


            elif val == 9:
                turn = turn
                playDeck.extend(discardDeck)
                discardDeck.clear()
                playDeck.shuffle()
                rule_card_val = playDeck[-1].val
                newRound = False

            else:
                # 4 of the same card, but no special rules
                pass

            
def winlose(player):
    """checks if player has one or lost after finishing cards and returns gameOver"""
    global player_list, win_order, lose_order, gameOver

    if turn_list[-1] == turn:
        lose_order.append(player)

    else:
        """if player finishes their cards without losing"""
        win_order.append(player)


    turn = nextTurn(turn, 0, clockwise, player_list)

    """adjusting for list changing when removing player"""
    curr_turn = player_list.index(player)
    if turn > curr_turn:
        turn -= 1

    player_list.remove(player)

    if len(player_list) == 1:
        """if only one player is left, the game is over"""
        win_order.append(player_list[0])
        gameOver = True


# --------------------------------------------------------------------------------------------------------------------------------------------
# MAIN GAME LOOP

def main_gameloop():
    """runs main game logic"""
    # GAME CONDITIONS AND VARAIBLES
    global rule_card_val, clockwise, attack, gameOver, newRound, skip, turn_player, play_list, playable_cards, playable_index, turn_list, gameStart, turn, player_list

    """WAIT UNTIL EVERYBODY HAS CONNECTED"""
    while len(player_list) < num_players:
        time.sleep(1)
        
    """WAIT UNTIL EVERYBOODY IS READY"""
    while gameReady(player_list) == False:
        time.sleep(1)
        
    #first turn
    for player in player_list:
        if player.turn == True:
            player.turn = False
            turn_list.append(player_list.index(player))
            turn = nextTurn(turn_list[0], skip, clockwise, player_list)

    while gameOver == False:
        time.sleep(0.25)
        for player in player_list:
            player.hand = sortDeck(player.hand)
            player.clockwise = clockwise
            player.eat = False
            
            if player == player_list[turn]:
                turn_player = player
                player.actions[0] = False #ie player's turn
                player.turn = True
                turn_list.append(turn)
        time.sleep(0.5)

        play_list.clear()
        last_cards.clear() # have to send last_cards to clients (if more than 1)

        if newRound == True:
            newRound = False
            attack = False
            playable_cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        elif newRound == False:
            playable_cards = playableCards(rule_card_val, attack)

        # early game
        if turn_player.hand:
            playable_index = [] # index of cards in hand that can be played
            while len(turn_player.hand) < 3:
                    if not gameDeck: break
                    turn_player.hand.append(gameDeck.drawCard())

            i = 0
            for card in turn_player.hand:
                if card.val in playable_cards:
                    playable_index.append(i)
                i += 1

            if playable_index:
                # check status of what can and can't be played and play
                turn_player.actions[1] = playable_index
                playHand(turn_player)
                while len(turn_player.hand) < 3:
                    if not gameDeck: break
                    turn_player.hand.append(gameDeck.drawCard())
                

            elif not playable_index and gameDeck:
                """if cannot play a card but can pick up"""
                drawNotPlayableHand(turn_player)        

            elif not playable_index and not gameDeck:
                """if cannot play a card and cannot pick up"""
                newRound = True

            if newRound == True:
                eat(turn_player)

        #midgame/endgame
        elif not turn_player.hand:

            playable_index = [] # index of cards in hand that can be played
            temp1 = [] #top_cards cards

            for i in range(3):
                for card in turn_player.top_cards[i]:
                    temp1.append(card)

            #middlegame / top_cards
            if temp1:
                middleGame(turn_player)
            
            #endgame
            elif not temp1 and (turn_player.bottom_cards[0] or turn_player.bottom_cards[1] or turn_player.bottom_cards[2]):
                endGame(turn_player)


        """tests if cards have been flipped"""
        flipping(turn_player)

        if newRound == False:
            last_cards.extend(playDeck[-(len(play_list)):])
            player.detail_cards = last_cards
            nextRules()

        # win lose condition
        if not turn_player.hand and not turn_player.bottom_cards and turn_player in player_list:
            """check for all win lose conditions except flipping 8s and returns none"""
            winlose(turn_player)

        turn_player.turn = False # do I use player.turn anywhere (don't confuse with data.turn)
        turn_player.actions = [True, False, False, False, False] #ie not turn_player's turn + remove information

        

    standings = []

    for player in win_order:
        standings.append(player.name)

    for i in range(len(lose_order)):
        standings.append(lose_order[-1].name)
