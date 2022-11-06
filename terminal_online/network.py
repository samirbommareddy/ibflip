import socket

HEADER = 1024
PORT = 5555
SERVER = socket.gethostbyname(socket.gethostname())
ADDR = (SERVER, PORT)
FORMAT = 'utf-8'
DISCONNECT_MESSAGE = "!DISCONNECT"
LOOP_SLEEP = 0.5
num_players = 2
