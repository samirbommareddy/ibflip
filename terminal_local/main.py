import random
import time

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
    def __init__(self, name):
        self.name = name
        self.hand = Deck()
        self.bottomCards = Deck()

        """each element in topcards is a list since cards can double up"""
        self.topCards = []
        for i in range(3):
            self.topCards.append(Deck())

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


def initialise_game(names_of_players):
    """takes list of names as parameter and returns list of those players as class objects of type Player"""
    playerList = []
    for i in range(len(names_of_players)):
        playerList.append(Player(names_of_players[i]))
    return playerList

def faceCardPrint(number):
    """returns J, Q, K, A for 11, 12, 13, 14 or number itself"""
    if number == 11:
        return "J"
    elif number == 12:
        return "Q"
    elif number == 13:
        return "K"
    elif number == 14:
        return "A"
    else: return number

def showTophand(playerList): #not finished
    """prints facup cards of players for opponents to see before beginning the game"""
    pass

def fixHand(playerList): #not finished
    """allows players to sort their hand and faceup cards before beginning game"""
    pass

def player_lowestCard(playerList): #not finished
    """returns int with index of player in playerlist and index of lowest card in player's hand"""
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
    
    turn = playerList.index(lowest_player)
    for card in lowest_player.hand:
        if card.suit == lowest_suit and card.val == lowest_val:
            index_of_card = lowest_player.hand.index(card)
    
    return turn, index_of_card

def eat(turn, player, playDeck, newRound):
    """cannot play and there are no more cards"""
    turn = nextTurn(turn, 0, clockwise, playerList)
    player.hand.extend(playDeck)
    playDeck.clear()
    newRound = True

    ###
    print("\n YOU LOSE THIS ROUND AND EAT THE PILE!!")
    ###

    return turn, newRound

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

def nextTurn(turn, skip, clockwise, playerList):
    """takes relevant turn parameters and returns index of player in player_list whose turn is next."""
    if clockwise == True:
        turn = ((turn + skip + 1) % len(playerList))
    if clockwise == False:
        turn = (turn - skip - 1) % len(playerList)
    return turn

def nextRules(turn, playDeck, discardDeck, play_list, clockWise, player_list, attack):
    
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
        turn = nextTurn(turn, skip, clockWise, player_list)

    return turn, clockWise, rule_card_val, attack, newRound


def playHand(play_list, playable_index, player, playDeck):
    """plays cards from players hand and returns play_list"""

    ###
    print("You can play the following cards: ", player.name, ":", playable_index)
    ###

    while True:

        play_list.clear()
        temp1 = []
        temp2 = []
        temp3 = []

        ###
        play_input = input("\nWhich card(s) would you like to play? (format = 'number, number' etc.) : ").split(", ")
        ###

        for x in play_input:
            if x.isdigit() == False: temp1.append(False)
            else: temp1.append(True)

        if all(temp1):
            for x in play_input: play_list.append(int(x))
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
            ###
            print("Incorrect input. Try again")
            ###

    return play_list

def drawNotPlayableHand(player, gameDeck, playable_cards, playable_index):
    """asks player to draw card if cannot play and returns newRound and playable_index"""
    while True:
                """allows only y or n as input"""

                ###
                draw_card = input("\nYou cannot play. Would you like to draw a card and test if it can be played? (y/n) : ")
                ###

                if draw_card == 'y':
                    player.hand.append(gameDeck.drawCard())

                    ###
                    print("You drew", player.hand[-1].suit, player.hand[-1].val)
                    print("\nYour hand is now: ")
                    for i in range(len(player.hand)):
                        print(i, ":", player.hand[i].suit, player.hand[i].val)
                    ###

                    if player.hand[-1].val in playable_cards:
                        playable_index.append(player.hand.index(player.hand[-1]))
                        newRound = False

                        ###
                        print("\nYou can play this card!")
                        ###

                        
                    else:
                        newRound = True

                        ###
                        print("\nYou cannot play this card.")
                        ###

                    break

                elif draw_card == 'n':
                    newRound = True
                    break

                else:
                    print("invalid input")
    return newRound, playable_index
"""--------------------------------------------------------------------------------------------------------------------------------------------"""

# setup players
names_of_players = ["SAMUEL L. JACKSON", "TONY MUCA", "JORDAN PETERSON"]
playerList = initialise_game(names_of_players)

# setup decks
"""gameDeck is the main deck that one DRAWS FROM, playDeck on PLAYS ON, discardDeck on DISCARDS TO"""
gameDeck = Deck()
playDeck = Deck()
discardDeck = Deck()

# setup gameDeck
gameDeck.build()
gameDeck.shuffle()

# setup players decks
for player in playerList:
    player.dealCards(gameDeck)

# GAME CONDITIONS AND VARAIBLES
clockwise = True
attack = False
gameOver = False
newRound = True

win_order = []
lose_order = []
turn_list = []
play_list = [] # list with indeces of card played each turn

WAIT_TIME = 0.25

# fix hand
"""players can choose change topcards from hand if they want"""
showTophand(playerList)
fixHand(playerList)

# who starts
"""player with lowest cards starts"""
turn, lowest_index = player_lowestCard(playerList)
###
print("\nIt is ", playerList[turn].name, "'s turn\n", sep="")
print("You have the lowest card at index", lowest_index)
###



while gameOver == False:

    player = playerList[turn]
    turn_list.append(turn)

    time.sleep(WAIT_TIME)

    ###
    print("\nIt is ", player.name, "'s turn", sep="")
    ###

    if newRound == True: #done
        newRound = False
        playable_cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        

        ###
        print("\nThis is a new round\n")
        ###

    elif newRound == False:

        last_turn = []
        for i in range(len(play_list)):
            last_turn.append(((playDeck[-(i+1)].suit), (playDeck[-(i+1)].val)))
        

        ###
        print("These are the cards that were played last turn (recent card last):", last_turn)
        ###

        playable_cards = playableCards(rule_card_val, attack)

    """so that indeces of old cards are removed"""
    play_list.clear()

    # earlygame
    if player.hand: #done

        playable_index = [] # index of cards in hand that can be played

        ###
        print("You have the following cards: ")
        ###

        for i in range(len(player.hand)):

            ###
            print(i, ":", player.hand[i].suit, player.hand[i].val)
            ###

            if player.hand[i].val in playable_cards:
                playable_index.append(i)       

    # check status of what can and can't be played and play

        if not playable_index and gameDeck:
            """if cannot play a card and gameDeck not empty"""
            newRound, playable_index = drawNotPlayableHand(player, gameDeck, playable_cards, playable_index)         

        elif not playable_index and not gameDeck:
            newRound = True
            
        elif playable_index:
            """can play"""
            newRound = False 

        if newRound == True:
            turn, newRound = eat(turn, player, playDeck, newRound)

        elif newRound == False:
            play_list = playHand(play_list, playable_index, player, playDeck)

            while len(player.hand) < 3:
                if not gameDeck: break
                player.hand.append(gameDeck.drawCard())
    
    #midgame/endgame
    elif not player.hand:

        playable_index = [] # index of cards in hand that can be played
        temp1 = [] #topcards cards

        for i in range(3):
            for card in player.topCards[i]:
                temp1.append(card)


        #middlegame / topcards
        if temp1:
            
            #playable
            for i in range(3):

                ###
                for card in player.topCards[i]:
                    print(i, ":", end=" ")
                    print(card.suit, card.val, "   ")
                ###
                if player.topCards[i]:
                    if player.topCards[i][0].val in playable_cards:
                        playable_index.append(i)

            if not playable_index:
                turn, newRound = eat(turn, player, playDeck, newRound)

            elif playable_index:
                """can play"""
                newRound = False 

                ###
                print("You can play the following cards: ", player.name, ":", playable_index,)
                ###

                while True:

                    ###
                    x = input("\nWhich card(s) would you like to play? (ONLY ONE INDEX) : ")
                    ###

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
                            ###
                            print("Invalid input.")
                            ###
                    else:
                        ###
                        print("Invalid input.")
                        ###


        #endgame
        elif not temp1 and player.bottomCards:

            ###
            print("\nYou now have only you bottom cards left")
            input("Press any key to continue...")      
            ###

            r = 0 # card that will be played from bottom cards
            # bottom cards will play in order (left to right)

            ###
            print("\nYou had a", player.bottomCards[r].suit, player.bottomCards[r].val)
            ###

            if player.bottom_cards[r].val not in playable_cards:
                turn, newRound = eat(turn, player, playDeck, newRound)

            elif player.bottom_cards[r].val in playable_cards:
                playDeck.extend((player.play(player.bottomCards, [r])))
                play_list.append(1) # only for counting number of cards played, 1 is meaningless here

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
                available_cards = 0
                for card in discardDeck:
                    if card.val == 3:
                        available_cards.append(card)
                if len(available_cards) >= len(playerList) - 1:
                    opponent_list = list(playerList)
                    opponent_list.remove(player)
                    for player in opponent_list:
                        cheatDeck(available_cards[0].suit, available_cards[0].val, opponent_list.hand, discardDeck)
                print("You flipped the 3s!")
        

            elif val == 4:
                turn = nextTurn(turn, 0, clockwise, playerList)
                for card in discardDeck:
                    if card.val == 3:
                        cheatDeck(card.suit, card.val, player.hand, discardDeck)
                        break # only give one 3
                print("You flipped the 4s!")

            elif val == 8:
                turn = nextTurn(turn, 0, clockwise, playerList)
                lose_order.append(player)
                playerList.remove(player)
                print("You lost by flipping the 8s")

            elif val == 9:
                turn = turn
                playDeck.extend(discardDeck)
                discardDeck.clear()
                playDeck.shuffle()
                rule_card_val = playDeck[0].val
                print("You flipped the 9s")
                print("Play on", playDeck[0].suit, playDeck[0].val)
                newRound = False

            else:
                # 4 of the same card, but no special rules
                pass

    # win lose condition
    if not player.hand and not player.bottomCards and player in playerList:
        """check for all win lose conditions except flipping 8s and returns none"""

        if turn_list[-1] == turn:
            lose_order.append(player)

            ###
            print("You lost!")
            ###

        else:
            """if player finishes their cards without losing"""
            win_order.append(player)

            ###
            print("Congratulations, you won!")
            ###

        turn = nextTurn(turn, 0, clockwise, playerList)
        playerList.remove(player)

        if len(playerList) == 1:
            """if only one player is left, the game is over"""
            newRound = True # to not activate nextRules 
            gameOver = True

    if newRound == False:
        turn, clockwise, rule_card_val, attack, newRound = nextRules(turn, playDeck, discardDeck, play_list, clockwise, playerList, attack)
