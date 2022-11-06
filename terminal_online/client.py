import socket
import time

HEADER = 1024
PORT = 5555
FORMAT = 'utf-8'
DISCONNECT_MESSAGE = "!DISCONNECT"
SERVER = "192.168.56.1"
ADDR = (SERVER, PORT)

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

#input("Press any key to start running...")
print("running...")

client.connect(ADDR)

# setup
msg = client.recv(HEADER).decode(FORMAT)
name = input(msg)
#name = "Sam"
client.send(name.encode(FORMAT))
playerID = client.recv(HEADER).decode(FORMAT)
print("PlayerID : " + playerID)
print("connected...")


while True:
    received_msg = client.recv(HEADER).decode(FORMAT)
    if received_msg[:4] == "----":
        asked_input = input(received_msg[4:])
        if asked_input == "":
            asked_input = "NoInput"
        client.send(asked_input.encode(FORMAT))
    else:
        print(received_msg)