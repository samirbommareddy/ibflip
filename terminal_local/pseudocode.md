class Card
class Deck
class Player

setup game
    define player turn order (list of player names)
    deal cards to players


allow players to fix hand (other players should see dealt face up cards)

which player starts

while game not over:
    turn = whose turn it is 
        #del later since it will be defined at the end of the loop for each turn
    
    #early-game
    if player has cards in hand

        if can play
            play card from hand
            while gameDeck:
                pick up cards if hand < 3
        else: choose to pick up (y/n)
            if y:
                show card to all players
                if can play
                    play
                else: eat
            else: eat

    if player does not have cards in hand (and there are no cards in gamedeck) - should not be necessary since player will pick up cards after each turn if                                                                           there are cards in gamedeck
        
        #middlegame
        if player has top cards
            if can play: play
            else: eat
        
        #endgame
        elif player has no topcards
            try playing bottom card
            if can play
                play
            else: eat
        
    if hasLost == True rules:
        player loses (add to loser list)
        if turn would land on player, it continues to the next person
            since only way to lose early is to land on yourself, turn = turn + 1 (clockwise dependant)
        remove player from playerlist
        if no. of players == 1: 
            add last player to playerlist
            break
        next_rules 


    elif hasWon == True :
        player wins (add to win list)
        if no. of players == 1: 
            add last player to playerlist
            break
        next rules (turn continues to next player as normal)
        remove player from playerlist
    
    elif hasFlipped == True (not 8s):
        turn = turn
        flip cards, new turn
    
    else:
        next rules based on card played


print order of players that won, last player, backwards of player lost