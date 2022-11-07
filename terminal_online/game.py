#todo
"""
- last turn cards: save in a list and then clear after printing out
- ASCII ART
- time.sleep to all input functions in game.py (not done yet)
- bugs
- consistent style of writing across
- check infodump (notes above last_turn)
- sort hand after each turn

"""




import random
import time
from network import *

class Card:
    """has attributes suit referring to diamonds, hearts etc and val referring to A, K, 2 etc (2-->14)"""
    def __init__(self, suit, val):
        self.suit = suit
        self.val = val

class Deck(list):
    """list which will be composed of objects of type Card"""
    def __init__(self):
        pass

    def build(self):
        """52 cards (4 suits of 13 cards each) with are added to deck (self)"""
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
    def __init__(self, id, client, name):
        self.id = id
        self.done = False
        self.turn = False
        self.client = client
        self.name = name
        self.hand = Deck()
        self.bottomCards = Deck()


        """each element in topcards is a list since cards can double up"""
        self.topCards = []
        for i in range(3):
            self.topCards.append(Deck())

        self.info_dump = []
        self.gamestart = False

    def dealCards(self, deck):
        """adds 3 cards to players' 3 decks each and removes from gameDeck"""
        for i in range(3):
            self.bottomCards.append(deck.drawCard())
            self.hand.append(deck.drawCard())
            self.topCards[i].append(deck.drawCard())

    def play(self, deck, play_list):
        """takes list of indexes of cards to be played from a deck as parameter
        and returns list with cards in order that they were played"""
        temp = []
        for i in play_list:
            temp.append(deck[i])
        for index in sorted(play_list, reverse=True):
            del deck[index]
        return temp

"""--------------------------------------------------------------------------------------------------------------------------------------------"""
#HELPER FUNCTIONS

def initialise_game(names_of_players):
    """takes list of names as parameter and returns list of those players as class objects of type Player"""
    playerList = []
    for i in range(len(names_of_players)):
        playerList.append(Player(names_of_players[i]))
    return playerList

def faceCardPrint(number):
    """returns J, Q, K, A for 11, 12, 13, 14 or number as str itself"""
    if number == 11:
        return "J"
    elif number == 12:
        return "Q"
    elif number == 13:
        return "K"
    elif number == 14:
        return "A"
    else: return str(number)

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

def showTophand(playerList): #not finished
    """prints facup cards of players for opponents to see before beginning the game"""
    pass

def player_lowestCard(playerList):
    """returns player in playerlist with lowest card and index of lowest card in player's hand"""
    lowest_val_order = [3, 6, 8, 9, 11, 12, 13, 14, 7, 2, 10, 4, 5]
    lowest_suit_order = ["Hearts", "Diamonds", "Clubs", "Spades"]

    lowest_val = 5
    lowest_suit = "Spades"
    lowest_player = None

    for player in playerList:
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
    
    #turn = playerList.index(lowest_player)
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

def nextTurn(current_turn, skip, clockwise, playerList):
    """takes relevant turn parameters and returns index of player in player_list whose turn is next."""
    if clockwise == True:
        nextTurn = ((current_turn + skip + 1) % len(playerList))
    if clockwise == False:
        nextTurn = (current_turn - skip - 1) % len(playerList)
    return nextTurn

def nextRules(turn, playDeck, discardDeck, play_list, clockWise, playerList, attack):
    
# establishes play parameters based on card(s) that were played and previous parameters

    turn_over = False
    rule_card_val = playDeck[-1].val
    skip = 0 # for use with 8s
    newRound = False

    while turn_over == False:

        if rule_card_val == 2:
            turn = turn
            turn_over = True

        elif rule_card_val == 3:
            if len(play_list) % 2 == 1: #isprime
                clockWise = not clockWise
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
    
    if rule_card_val not in [2, 10]:
        turn = nextTurn(turn, skip, clockWise, playerList)

    return turn, clockWise, rule_card_val, attack, newRound

def cardName(card):
    """Returns string with card value and card suit"""
    return faceCardPrint(card.val) + " of " + card.suit 

def oppList(player):
    """returns list with opponents for player"""
    global playerList
    temp = list(playerList)
    temp.remove(player)
    return temp

def readval(val):
    if val == 11: return "J"
    elif val == 12: return "Q"
    elif val == 13: return "K"
    elif val == 14: return "A"
    else: return str(val)
"""--------------------------------------------------------------------------------------------------------------------------------------------"""
#NETWORK FUNCTIONS

def opp_done(player, playerList):
    """checks if attribute done for all players other thatn parameter player is True or False. Returns True if all are True. Else False"""
    check_list = []
    temp = list(playerList)
    temp.remove(player)
    for opp in temp:
        if opp.done == True: check_list.append(True)
        else: check_list.append(False)
    if all(check_list) == True: return True
    else: return False
        
def waiting(TIME, player, playerList):
    """runs while loop until opp_done returns true"""
    """repeated inside while loop to avoid coincidence error"""
    player.done = True
    wait = False
    while opp_done(player, playerList) == False or wait == False:
        time.sleep(TIME/3)
        wait = opp_done(player, playerList)
        time.sleep(TIME/3)
    time.sleep(TIME)
    player.done = False

def gameReady(playerList):
    """if all players in playerlist are ready, returns ready"""
    temp = []
    for player in playerList:
        if player.gamestart == True: temp.append(True)
        else: temp.append(False)
    return all(temp)
"""--------------------------------------------------------------------------------------------------------------------------------------------"""
#GAMEPLAY FUNCTIONS

def terminal_fixhand(player, clientsocket):

    error_string = "\n!!You have not given a valid input. Try again.!!\n"
    keep_fixing = True
    while keep_fixing == True:

        time.sleep(LOOP_SLEEP)
        msg = ["\nYour faceup cards are: \n"]
        for i in range(3):
            msg.append(str(i) + " : ")
            for k in range(len(player.topCards[i])):
                msg.append(player.topCards[i][k].suit + " " + faceCardPrint(player.topCards[i][k].val) + ", ")
            msg.append("\n")
    
        msg.append("\nYour hand is: \n")
        for i in range(3):
            msg.append(str(i) + " : " + str(player.hand[i].suit) + " " + faceCardPrint(player.hand[i].val) + "\n")     

        message = "".join(msg)
        clientsocket.send(message.encode(FORMAT))

        clientsocket.send("----Do you want to fix (switch/double up) any cards? (y/n) : ".encode(FORMAT))
        input_decision = clientsocket.recv(HEADER).decode(FORMAT)

        if input_decision == 'n':
            clientsocket.send("\nOk. Got it! Exiting...\n\n".encode(FORMAT))
            keep_fixing = False
            break
            
        elif input_decision == 'y':

            clientsocket.send("----\nWhich card in your hand do you want to fix? (0, 1, 2) : ".encode(FORMAT))
            index_hand = clientsocket.recv(HEADER).decode(FORMAT)
            clientsocket.send("----\nWhich card index of your faceup cards do you want to fix? (0, 1, 2) : ".encode(FORMAT))
            index_top = clientsocket.recv(HEADER).decode(FORMAT)
            clientsocket.send("----\nDo you want to switch or double? (s/d) : ".encode(FORMAT))
            switch_decision = clientsocket.recv(HEADER).decode(FORMAT)

            check_true = []

            if switch_decision not in ['s', 'd']:
                clientsocket.send(error_string.encode(FORMAT))
                check_true.append(False)


            for index in [index_hand, index_top]:
                if index.isdigit() == False or index not in ["0", "1", "2"]: check_true.append(False)
                else: check_true.append(True)

            if all(check_true):
                index_hand = int(index_hand)
                index_top = int(index_top)

                if switch_decision == 's':
                    if len(player.topCards[index_top]) > 1:
                        check_true.append(False)

                if switch_decision == 'd':
                    if player.topCards[index_top][0].val != player.hand[index_hand].val:
                        check_true.append(False)

            if all(check_true):
                
                if switch_decision == 's':
                    player.hand.insert(index_hand, player.topCards[index_top].pop(0))
                    player.topCards[index_top].append(player.hand.pop(index_hand + 1))

                elif switch_decision =='d':
                    player.topCards[index_top].append(player.hand.pop(index_hand))
                    player.hand.append(gameDeck.pop())

                msg = ["\nYour faceup cards are: \n"]
                for i in range(3):
                    msg.append(str(i) + " : ")
                    for k in range(len(player.topCards[i])):
                        msg.append(player.topCards[i][k].suit + " " + faceCardPrint(player.topCards[i][k].val) + "     ")
                    msg.append("\n")
            
                msg.append("\nYour hand is: \n")
                for i in range(3):
                    msg.append(str(i) + " : " + str(player.hand[i].suit) + " " + faceCardPrint(player.hand[i].val) + "\n")     

                message = "".join(msg)
                clientsocket.send(message.encode(FORMAT))

                while True:
                    clientsocket.send("----\nDo you want to continue fixing cards? (y/n) : ".encode(FORMAT))
                    decision_continue = clientsocket.recv(HEADER).decode(FORMAT)

                    if decision_continue not in ["y", "n"]:
                        clientsocket.send(msg.encode(FORMAT))
                    if decision_continue == "y":
                        clientsocket.send("\nOk. Got it! Continuing...\n".encode(FORMAT))
                        keep_fixing = True
                        break
                    elif decision_continue == "n":
                        clientsocket.send("\nOk. Got it! Exiting...\n\n".encode(FORMAT))
                        keep_fixing = False
                        break
                        
            else:
                clientsocket.send(error_string.encode(FORMAT))
        else:
            clientsocket.send(error_string.encode(FORMAT))

def gamestart_lowestcard(player, playerList, clientsocket):
    lowest_player, card_index = player_lowestCard(playerList)
    if player == lowest_player:
        player.turn = True

    if player.turn == True:

        clientsocket.send(f"\nYou have the lowest card -- {cardName(player.hand[card_index])}".encode(FORMAT))
        clientsocket.send("----\nPress enter to play it...".encode(FORMAT))
        clientsocket.recv(HEADER).decode(FORMAT)

        playDeck.append(player.hand.pop(player_lowestCard(playerList)[1]))
        player.hand.append(gameDeck.pop())

    elif player.turn == False:
        clientsocket.send(f"\n{lowest_player.name} has the lowest card".encode(FORMAT))
        clientsocket.send(f"Waiting for {lowest_player.name} to play...".encode(FORMAT))

    waiting(1, player, playerList)

    if player.turn == True:
        clientsocket.send(f"\n You played the {cardName(playDeck[-1])}\n".encode(FORMAT))
    elif player.turn == False:
        clientsocket.send(f"\n {lowest_player.name} played the {cardName(playDeck[-1])}\n".encode(FORMAT))

def infoDump():
    """adds all information about a round to player.info_dump"""
    global playerList, last_cards, playDeck, discardDeck, gameDeck, turn_player, turn
    message = []

    for player in playerList:
        message.clear()

        #add header
        message.append("\n" + "-"*125 + "\n")

        if newRound == True:
            message.append("\nThis is a new round!\n")
            
        if player.turn == True:
            message.append("\nIt is YOUR turn!\n")
        else:
            message.append(f"\nIt is {turn_player.name}'s turn\n")

        if player.hand:
            i = 0
            message.append("\nThese are the cards in your hand: \n")
            for card in player.hand:
                message.append(str(i) + " : " + cardName(card) + "\n")
                i +=1
        else:
            message.append("\nYou have NO MORE CARDS in your HAND!\n")

        temp = []
        for i in range(3):
            if player.topCards[i]: temp.append(True)
        
        if temp:
            message.append("\nThese are your FACE UP cards\n")
            for i in range(3):
                message.append(str(i) + " : ")
                if player.topCards[i]:
                    for card in player.topCards[i]:
                        message.append(cardName(card) + ", ")
                else: message.append("empty")
                message.append("\n")
        else: 
            message.append("\nYou have NO MORE FACE UP cards\n")

        message.append(f"\nYou have {len(player.bottomCards)} FACE DOWN cards left.\n")
        message.append(f"\nNUMBER OF CARDS:\nGameDeck : {len(gameDeck)}\nPlayDeck : {len(playDeck)}\nGarbage : {len(discardDeck)}\n")

        #WILL GIVE ERROR SINCE LAST_CARDS NOT DEFINED, FIRST ROUND IS ALSO NOT NEW ROUND
        if newRound == False:
            message.append("\n Cards played last turn : ")
            for card in last_cards:
                message.append(cardName + " ,  ")
        
        temp = list(playerList)
        temp.remove(player)

        for opp in temp:

            message.append(f"\n{opp.name} :\nNO. OF CARD IN HAND : {len(opp.hand)}")

            temp2 = []
            for i in range(3):
                if opp.topCards[i]: temp2.append(True)
            if temp2:
                message.append("\nFace up cards :\n")
                for i in range(3):
                    message.append(str(i) + " : ")
                    if opp.topCards[i]:
                        for card in opp.topCards[i]:
                            message.append(cardName(card) + ", ")
                    else: message.append("empty")
                    message.append("\n")
            else: 
                message.append(f"{opp.name} has NO MORE FACE UP cards\n")
            
            message.append(f'FACE DOWN cards : {len(opp.bottomCards)}')

        #add footer
        message.append("\n\n" + "-"*125 + "\n")

        player.info_dump = "".join(message)
        player.client.send(player.info_dump.encode(FORMAT))

def player_gameloop(player, clientsocket):

    # GAME CONDITIONS AND VARAIBLES
    global rule_card_val, clockwise, attack, gameOver, newRound, skip, turn_player, play_list, turn_list, gameStart, turn

    rule_card_val = playDeck[-1].val
    if rule_card_val == 3:
        clockwise == False
    elif rule_card_val == 8:
        skip = 1
        
    """player.turn is still True from gamestart_lowestcard"""
    if player.turn == True:
        turn_list.append(playerList.index(player))
        turn = nextTurn(turn_list[0], skip, clockwise, playerList)

    while gameOver == False:

        if player == playerList[turn]:
            turn_player = player
            player.turn = True
            turn_list.append(turn)

        if newRound == True:
            clientsocket.send("\nThis is a new round.\n".encode(FORMAT))
        clientsocket.send(f"\nIt is {turn_player.name}'s turn!\n".encode(FORMAT))


        time.sleep(30)
        player.turn = False
    pass

def playHand(play_list, playable_index, player, playDeck):
    """plays cards from players hand and returns play_list"""

    player.client.send(f"\nYou can play the following cards : {playable_index}".encode(FORMAT))
    
    while True:
        play_list.clear()
        temp1 = []
        temp2 = []
        temp3 = []

        player.client.send("----\nWhich card(s) would you like to play? (format = 'number, number' etc.) : ".encode(FORMAT))
        play_input = player.client.recv(HEADER).decode(FORMAT)

        for x in play_input.split(", "):
            if x.isdigit() == False: temp1.append(False)
            else: temp1.append(True)

        if all(temp1):
            #for x in play_input: 
            play_list.append(int(x))
            for index in play_list:
                if index not in playable_index: temp2.append(False)
                else: temp2.append(True)
            
            if all(temp2):
                """check that if two cards are played, they are of the same rank"""
                card_val = player.hand[play_list[0]].val # first playable card
                for index in play_list:
                    if player.hand[index].val != card_val: temp3.append(False)
                    else: temp3.append(True)
                    
                if all(temp3):
                    playDeck.extend((player.play(player.hand, play_list)))
                    break
        if not all(temp1) or not all(temp2) or not all(temp3): 
            
            player.client.send("Incorrect input. Try again.".encode(FORMAT))

    return play_list

def drawNotPlayableHand(player, gameDeck, playable_cards, playable_index):
    """asks player to draw card if cannot play and returns newRound and playable_index"""

    global turn_player, playerList

    while True:
        """allows only y or n as input"""
        
        player.client.send("\nYou cannot play. Would you like to draw a card and test if it can be played? (y/n) : ".encode(FORMAT))
        draw_card = player.client.recv(HEADER).decode(FORMAT)

        if draw_card == 'y':
            player.hand.append(gameDeck.drawCard())

            ###
            for opp in oppList(player):
                opp.client.send(f"{player.name} drew a {cardName(player.hand[-1])}".encode(FORMAT))
            
            player.client.send("\nYour hand is now: ".encode(FORMAT))
            for i in range(len(player.hand)):
                player.client.send(str(i) + " : " + cardName(player.hand[i]).encode(FORMAT))

            if player.hand[-1].val in playable_cards:
                playable_index.append(player.hand.index(player.hand[-1]))
                newRound = False
                
            else:
                newRound = True

            break

        elif draw_card == 'n':
            newRound = True
            break

        else:
            player.client.send("INVALID INPUT".encode(FORMAT))

    return newRound, playable_index

def eat(turn, clockwise, player, playDeck, newRound):
    """cannot play and there are no more cards"""
    turn = nextTurn(turn, 0, clockwise, playerList)
    player.hand.extend(playDeck)
    playDeck.clear()
    newRound = True

    player.client.send("\n YOU LOSE THIS ROUND AND EAT THE PILE!!".encode(FORMAT))

    return turn, newRound

def middleGame(play_list, playable_index, playable_cards, player, playDeck):

    player.client.send("\nYour hand is empty. You have your face up cards left\n".encode(FORMAT))

    #playable
    for i in range(3):
        if player.topCards[i]:
            if player.topCards[i][0].val in playable_cards:
                playable_index.append(i)

    if not playable_index:
        turn, newRound = eat(turn, clockwise, turn_player, playDeck, newRound)

    elif playable_index:
        """can play"""
        newRound = False 
        
        player.client.send(f"You can play the following cards: {playable_index}".encode(FORMAT))

        while True:

            player.client.send("\nWhich card(s) would you like to play? (ONLY ONE INDEX) : ".encode(FORMAT))
            x = player.client.recv(HEADER).decode(FORMAT)

            if x.isdigit() == True:
                x = int(x)
                if x in playable_index:
                    playDeck.extend(player.topCards[x])
                    for card in player.topCards[x]:
                        # only for counting number of cards - required for 3 and 8
                        play_list.append(1)
                    player.topCards[x].clear()
                    break
                else:
                    player.client.send("INVALID INPUT".encode(FORMAT))
            else:
                player.client.send("INVALID INPUT".encode(FORMAT))
    return turn, newRound, play_list

def endGame(play_list, playable_cards, player):

    global playDeck, playerList

    player.client.send("\nYou now have only you bottom cards left\n".encode(FORMAT))
    player.client.send("----Press any key to continue...".encode(FORMAT))
    player.client.recv(HEADER).decode(FORMAT)

    r = 0 # card that will be played from bottom cards
    # bottom cards will play in order (left to right)

    player.client.send(f"\nYou had a : {cardName(player.bottomCards[r])}".encode(FORMAT))
    for opp in oppList(player):
        opp.client.send(f"{player.name} attempted to play from his face down cards. He had a {cardName(player.bottomCards[r])}".encode(FORMAT))


    if player.bottomCards[r].val not in playable_cards:

        turn, newRound = eat(turn, player, playDeck, newRound)

    elif player.bottomCards[r].val in playable_cards:

        player.client.send("You were able to play!".encode(FORMAT))

        playDeck.extend((player.play(player.bottomCards, [r])))
        play_list.append(1) # only for counting number of cards played, 1 is meaningless here

    return turn, newRound, play_list

def flipping(player):
    """tests if cards have been flipped and returns turn, clockwise, newRound, rule_card_val"""
    global playDeck, discardDeck, playerList, lose_order

    # flipping
    if len(playDeck) >= 4:

        temp1 = []

        for i in range(3):
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
                if len(available_cards) >= len(playerList) - 1:
                    for opp in oppList(player):
                        cheatDeck(available_cards[0].suit, available_cards[0].val, player.hand, discardDeck)
        

            elif val == 4:
                turn = nextTurn(turn, 0, clockwise, playerList)
                for card in discardDeck:
                    if card.val == 3:
                        cheatDeck(card.suit, card.val, player.hand, discardDeck)
                        break # only give one 3

            elif val == 8:
                turn = nextTurn(turn, 0, clockwise, playerList)
                lose_order.append(player)
                playerList.remove(player)
                all.client.send(f"!!!{player.name} LOST BY FLIPPING THE 8S!!!".encode(FORMAT))
                ####ASCIII ART#####

            elif val == 9:
                turn = turn
                playDeck.extend(discardDeck)
                discardDeck.clear()
                playDeck.shuffle()
                rule_card_val = playDeck[0].val
                for all in playerList:
                    all.client.send(f"9s flipped : Play on {cardName(playDeck[0])}".encode(FORMAT))
                newRound = False

            else:
                # 4 of the same card, but no special rules
                pass

            player.client.send("You FLIPPED the {readval(val)}s!!".encode(FORMAT))
            for opp in oppList(player):
                opp.client.send
                opp.client.send(f"{player.name} FLIPPED the {readval(val)}s!!".encode(FORMAT))
            
            return turn, clockwise, newRound, rule_card_val
            
def winlose(player):
    """checks if player has one or lost after finishing cards and returns gameOver"""
    global playerList, win_order, lose_order, gameOver

    if turn_list[-1] == turn:
        lose_order.append(player)

        player.client.send("You LOST!!".encode(FORMAT))
        for opp in oppList(player):
            opp.client.send
            opp.client.send(f"{player.name} LOST!!".encode(FORMAT))

    else:
        """if player finishes their cards without losing"""
        win_order.append(player)

        player.client.send("You WON!!".encode(FORMAT))
        for opp in oppList(player):
            opp.client.send
            opp.client.send(f"{player.name} WON!!".encode(FORMAT))

    turn = nextTurn(turn, 0, clockwise, playerList)

    """adjusting for list changing when removing player"""
    curr_turn = playerList.index(player)
    if turn > curr_turn:
        turn -= 1

    playerList.remove(player)

    if len(playerList) == 1:
        """if only one player is left, the game is over"""
        win_order.append(playerList[0])
        gameOver = True
    
    return gameOver

"""--------------------------------------------------------------------------------------------------------------------------------------------"""
# MAIN GAME LOOP

def main_gameloop():

    # GAME CONDITIONS AND VARAIBLES
    global rule_card_val, clockwise, attack, gameOver, newRound, skip, turn_player, play_list, turn_list, gameStart, turn, playerList

    """WAIT UNTIL EVERYBODY HAS CONNECTED"""
    while len(playerList) < num_players:
        time.sleep(1)
        

    """WAIT UNTIL EVERYBOODY IS READY"""
    while gameReady(playerList) == False:
        time.sleep(1)
        
    #first turn
    for player in playerList:
        if player.turn == True:
                turn_list.append(playerList.index(player))
                turn = nextTurn(turn_list[0], skip, clockwise, playerList)

    while gameOver == False:

        player.turn = False
        for player in playerList:
            if player == playerList[turn]:
                turn_player = player
                player.turn = True
                turn_list.append(turn)

        infoDump()
        play_list.clear()

        if newRound == True:
            newRound = False
            playable_cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        elif newRound == False:
            playable_cards = playableCards(rule_card_val, attack)

        # early game
        if turn_player.hand:
            playable_index = [] # index of cards in hand that can be played

            i = 0
            for card in turn_player.hand:
                if card.val in playable_cards:
                    playable_index.append(i)
                    i += 1       

        # check status of what can and can't be played and play

            if not playable_index and gameDeck:
                """if cannot play a card and but can pick up"""
                newRound, playable_index = drawNotPlayableHand(turn_player, gameDeck, playable_cards, playable_index)         

            elif not playable_index and not gameDeck:
                """if cannot play a card and cannot pick up"""
                newRound = True
                
            elif playable_index:
                """can play"""
                newRound = False 

            if newRound == True:
                turn, newRound = eat(turn, clockwise, turn_player, playDeck, newRound)

            elif newRound == False:
                play_list = playHand(play_list, playable_index, turn_player, playDeck)

                while len(turn_player.hand) < 3:
                    if not gameDeck: break
                    turn_player.hand.append(gameDeck.drawCard())
        
        #midgame/endgame
        elif not turn_player.hand:

            playable_index = [] # index of cards in hand that can be played
            temp1 = [] #topcards cards

            for i in range(3):
                for card in turn_player.topCards[i]:
                    temp1.append(card)

            #middlegame / topcards
            if temp1:
                turn, newRound, play_list = middleGame(play_list, playable_index, playable_cards, player, playDeck)
            
            #endgame
            elif not temp1 and player.bottomCards:
                turn, newRound, play_list = endGame(play_list, playable_cards, player)

        """tests if cards have been flipped"""
        turn, clockwise, newRound, rule_card_val = flipping(player)

        if newRound == False:
            turn, clockwise, rule_card_val, attack, newRound = nextRules(turn, playDeck, discardDeck, play_list, clockwise, playerList, attack)

        # win lose condition
        if not player.hand and not player.bottomCards and player in playerList:
            """check for all win lose conditions except flipping 8s and returns none"""
            winlose(player)

    standings = []

    for player in win_order:
        standings.append(player.name)

    for i in range(len(lose_order)):
        standings.append(lose_order[-1].name)

    print(standings)
"""--------------------------------------------------------------------------------------------------------------------------------------------"""


# setup players
playerList = []

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
