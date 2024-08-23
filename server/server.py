import socket 
import threading
import pickle
import time
from game import *
from pickle_objects import clientGame, clientOpponent, clientPlayer

SERVER = "192.168.1.69"
PORT = 0000
  
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((SERVER, PORT))
server.settimeout(5.0)

def updateClientGame(game_stage, player):
    """returns object of type clientGame containing game information to send to client"""
    global player_list, playDeck, gameDeck, discardDeck
    """returns data of type ClientGame that contains everything required to play the game.
    This data is sent to the client from the server"""
    # card data is not compatible with pygame as of now

    data = clientGame(game_stage, player.clockwise, playDeck, len(gameDeck), len(discardDeck))

    data.player = clientPlayer()
    data.player.actions = player.actions
    data.detail_cards = player.detail_cards
    data.player.hand = player.hand
    data.player.top_cards = player.top_cards
    for i in range(3):
        if player.bottom_cards[i]: data.player.is_bottom_cards[i] = True
        else: data.player.is_bottom_cards[i] = False
    
    p_ind = player_list.index(player)
    opp_list = []
    game_opp_list = player_list[p_ind:] + player_list[:p_ind]
    game_opp_list.pop(0)

    for game_opp in game_opp_list:
        opp = clientOpponent(game_opp.name, len(game_opp.hand))
        opp.top_cards = game_opp.top_cards
        opp.eat = game_opp.eat
        for i in range(3):
            if game_opp.bottom_cards[i]: opp.bottom_cards[i] = True
            else: opp.bottom_cards[i] = False
        opp_list.append(opp)
    data.opp_list = opp_list
    for opp in game_opp_list:
            if opp.turn == True: data.turn = game_opp_list.index(opp)
            elif player.turn == True:
                data.turn = 'own'
                break
    return data

def handle_client(clientsocket, addr):
    """"communicates with client"""
    global player_list, clockwise, playDeck, gameDeck, discardDeck
    print(f"[NEW CONNECTION] {addr} connected.")
    
    # client has connected
    data = clientGame('connect', None, None, None, None)
    clientsocket.sendall(pickle.dumps(data))
    clientsocket.settimeout(5.0)

    while True:
        try:
            name = pickle.loads(clientsocket.recv(4096))
            print("name received: ", name)
            break
        except: pass

    print("[WAITING] Waiting for other players to connect!")
    # WAIT UNTIL EVERYBODY HAS CONNECTED
    while threading.active_count() - 2 < num_players:
        data = clientGame('wait_for_opps', None, None, None, None)
        try: clientsocket.sendall(pickle.dumps(data))
        except: pass
        
    player = Player(clientsocket, name)
    player_list.append(player)
    player.dealCards(gameDeck)

    print(name, "player fixhand starting")
    client_data = 'no_move'
    while True:
        time.sleep(0.1)
        data = updateClientGame('fix_hand', player)
        try: clientsocket.sendall(pickle.dumps(data))
        except: pass
        try:
            client_data = pickle.loads(clientsocket.recv(4096))
        except: pass
        if client_data[3] == True:
            break
        elif client_data != "no_move": 
            fixHand(player, client_data)

    waiting(0.2, player, player_list)

    # player with lowest card plays
    gamestart_lowestcard()
    data = updateClientGame('main_game', player)
    player.client_data = '____NODATA'
    clientsocket.sendall(pickle.dumps(data))

    player.gamestart = True
    while gameOver == False:
        time.sleep(0.5)
        data = updateClientGame('main_game', player)
        try: 
            clientsocket.sendall(pickle.dumps(data))
        except: pass

        try:
            player.client_data = pickle.loads(player.client.recv(4096))
        except:
            player.client_data = '____NODATA'

    clientsocket.close()


def network_start():
    """creates a thread for each connection"""
    server.listen(num_players)
    print(f"[LISTENING] Server is listening on {SERVER}")
    while True:
        time.sleep(0.1)
        try:
            clientsocket, addr = server.accept()
            threading.Thread(target=handle_client, args=(clientsocket, addr)).start()
            print(f"[ACTIVE CONNECTIONS] : {threading.active_count() - 2}")
        except:
            pass

def main():
    print("[STARTING] server is starting...")
    threading.Thread(target=main_gameloop).start()
    network_start()


if __name__ == "__main__":
    main()
