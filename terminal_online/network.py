import socket

HEADER = 1024
PORT = 8080
SERVER = "192.168.0.202"
ADDR = (SERVER, PORT)
FORMAT = 'utf-8'
DISCONNECT_MESSAGE = "!DISCONNECT"
LOOP_SLEEP = 0.5
num_players = 3

print(SERVER)