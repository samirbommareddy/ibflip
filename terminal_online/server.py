import socket 
import threading
from game import *
from network import *


player_count = 0

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(ADDR)

def handle_client(clientsocket, addr):

    print(f"[NEW CONNECTION] {addr} connected.")

    global player_count
    playerID = player_count
    player_count += 1

    print("[WAITING] Waiting for other players to connect!")
    while threading.activeCount() - 1 < num_players:
        time.sleep(0.5)
        """WAIT UNTIL EVERYBODY HAS CONNECTED"""


    print("\n CREATED PLAYER")
    player = Player(playerID, clientsocket, "need_name")
    playerList.append(player)
    player.dealCards(gameDeck)

    # setup game for client
    clientsocket.send("What is your name? : ".encode(FORMAT))
    name = clientsocket.recv(HEADER).decode(FORMAT)
    print(f"[CLIENT] : {addr}, PlayerID : {playerID}, Name : {name}")
    player.name = name
    clientsocket.send(str(playerID).encode(FORMAT))
    clientsocket.send("Waiting for other players...".encode(FORMAT))

    waiting(2, player, playerList)
    
    # allow player to fix hand
    terminal_fixhand(player, clientsocket)
    clientsocket.send("\nYou've fixed your hand!\nWaiting on opponents...".encode(FORMAT))
    
    waiting(2, player, playerList)

    clientsocket.send("\nEveryone has fixed their hands.".encode(FORMAT))
    clientsocket.send("----Press enter to start... ".encode(FORMAT))
    print(addr, ":", clientsocket.recv(HEADER).decode(FORMAT))
    clientsocket.send("Waiting for other players...".encode(FORMAT))

    waiting(2, player, playerList)

    """start_string = "IBFlip Game Starting"
    for i in range(len("IBFlip Game Starting")):
        time.sleep(1)
        clientsocket.send((" ."*i + start_string[i] + " ."*(len(start_string) - i)).encode(FORMAT))"""

    print("here now\n")

    gamestart_lowestcard(player, playerList, clientsocket)

    player.gamestart = True

    connected = True
    while connected:
        print(f"[{addr}]: {player.name} - [CONNECTED]")
        if gameOver == True:
            connected = False
            time.sleep(10)
        time.sleep(1)

    clientsocket.close()
        

def network_start():
    server.listen(num_players)
    print(f"[LISTENING] Server is listening on {SERVER}")
    while True:
        clientsocket, addr = server.accept()
        print("connection accepted")
        thread = threading.Thread(target=handle_client, args=(clientsocket, addr))
        thread.start()
        print(f"[ACTIVE CONNECTIONS] {threading.activeCount() - 1}")

def main():
    print("[STARTING] server is starting...")
    gameloop = threading.Thread(target=main_gameloop)
    gameloop.start()
    network_start()


if __name__ == "__main__":
    main()
