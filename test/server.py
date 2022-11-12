import socket 
import threading
from network import *


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(ADDR)

def handle_client(clientsocket, addr):

    print(f"[NEW CONNECTION] {addr} connected.")


   
    clientsocket.send("What is your name? : ".encode(FORMAT))

    connected = True
    while connected:
        clientsocket.send("What is your name? : ".encode(FORMAT))
        print(f"[{addr}]: {player.name} - [CONNECTED]")

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
