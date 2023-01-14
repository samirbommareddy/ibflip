"""file runs two threads indefinately to 1. communicate with server and 2. update pygame display"""
import sys
import time
import threading
import socket
import pickle
import pygame
from pickle_objects import *


POKER_GREEN = (53, 101, 77)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
BLUE = (0, 0, 128)
AMBER =(255, 191, 0)
COLOUR_ACTIVE = (255, 0, 0)
COLOUR_INACTIVE = (150, 0, 0)

FPS = 60

SERVER = "enter_server_ip"
PORT = 0000
ADDR = (SERVER, PORT)
DATA_TIME = 0.1

pygame.init()
win = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("IB-Flip")
clock = pygame.time.Clock()
font = pygame.font.SysFont('arial', 32)
initCardDict()

title_screen = True
offset_x, offset_y = None, None
send_data = "nothing_yet"
data = "____NODATA"
angle = 0
cur_page_index = 0


left_arrow = pygame.image.load('assets/arrow-circle-right.png').convert_alpha()
left_arrow = pygame.transform.scale(left_arrow, (card_height//3, card_height//3))
left_arrow = pygame.transform.rotate(left_arrow, 180.0)
left_arrow_rect = left_arrow.get_rect()

right_arrow = pygame.image.load('assets/arrow-circle-right.png').convert_alpha()
right_arrow = pygame.transform.scale(right_arrow, (card_height//3, card_height//3))
right_arrow_rect = right_arrow.get_rect()

circle_arrow = pygame.image.load('assets/circle_arrows.png').convert_alpha()
circle_arrow_anticl = pygame.transform.scale(circle_arrow, (2.25 * card_height, 2.25 * card_height))
circle_arrow_cl = pygame.transform.flip(circle_arrow_anticl, True, False)


class InputBox:
    """Box which can take text input"""
    def __init__(self, center_coords, name):
        self.colour = COLOUR_INACTIVE
        self.text = ''
        self.surface = font.render(self.text, True, self.colour)
        self.rect = self.surface.get_rect()
        self.rect.center = center_coords
        self.active = False
        self.name = name
        self.name_surface = font.render(self.name, True, 'white')
        self.name_rect = self.name_surface.get_rect()

    def check_input(self, event):
        """checks for wither mouse input to select box or if a key has been pressed"""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.active = True
                self.colour = COLOUR_ACTIVE
            elif not self.rect.collidepoint(pygame.mouse.get_pos()):
                self.active = False
                self.colour = COLOUR_INACTIVE
        if event.type == pygame.KEYDOWN:
            if self.active:
                if event.key == pygame.K_RETURN:
                    self.done = True
                elif event.key == pygame.K_BACKSPACE:
                    self.text = self.text[:-1]
                else:
                    self.text += event.unicode
                self.surface = font.render(self.text, True, 'white')

    def update(self):
        """updates text inside box with input"""
        self.rect.width = max(200, self.surface.get_width()+10)
        self.name_rect.right = self.rect.left - 10
        self.name_rect.centery = self.rect.centery

    def draw(self, win):
        """draws box onto win"""
        win.blit(self.surface, (self.rect.topleft))
        pygame.draw.rect(win, self.colour, self.rect, 4)
        win.blit(self.name_surface, (self.name_rect.topleft))


class TextButton:
    """Button that is clickable"""
    def __init__(self, center_coords, text):
        self.colour = COLOUR_INACTIVE
        self.surface = font.render(text, True, 'white')
        self.rect = self.surface.get_rect()
        self.rect.center = center_coords
        self.active = False
        self.box_rect = pygame.rect.Rect(0, 0, (self.rect.width + 10), self.rect.height + 10)
        self.box_rect.center = center_coords
    
    def check_input(self, event):
        """checks if button has been clicked. Returns None"""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.active = True
                self.colour = COLOUR_ACTIVE
            elif not self.rect.collidepoint(pygame.mouse.get_pos()):
                self.active = False
                self.colour = COLOUR_INACTIVE
    
    def draw(self, win):
        """draws button onto win and returns None"""
        pygame.draw.rect(win, self.colour, self.box_rect, 4)
        win.blit(self.surface, (self.rect.topleft))


get_name = InputBox((WIDTH//2, HEIGHT//3), "Name: ")
get_ip = InputBox((WIDTH//2, HEIGHT//2), "IP: ")
get_port = InputBox((WIDTH//2, 2*HEIGHT//3), "Port: ")
title_boxes = [get_name, get_ip, get_port]
title_continue = TextButton((WIDTH//2, 4*HEIGHT//5), "CONTINUE")
fixhand_done = TextButton((WIDTH - WIDTH//10, hand_height), "DONE")
draw_yes = TextButton((7*WIDTH//10, playDeck_topleft[1]), "DRAW AND TRY")
draw_no = TextButton((7*WIDTH//10, playDeck_topleft[1] + card_height), "EAT")


def drawGameDecks():
    """takes data as input and renders gameDeck on pygame win"""
    # blit pos is different from rect pos
    global data, win, angle
    gameDeck_text = font.render(f"DRAW PILE: {data.len_gameDeck}", True, "white")
    discard_text = font.render(f"GARBAGE: {data.len_discardDeck}", True, "white")
    discard_rect = discard_text.get_rect()
    discard_rect.bottom = playDeck_topleft[1] + card_height

    if data.playDeck: win.blit(data.playDeck[-1].surface, playDeck_topleft)
    win.blit(gameDeck_text, (4*WIDTH//5, playDeck_topleft[1]))
    win.blit(discard_text, (4*WIDTH//5, discard_rect.top))
    #CHANGING ARROW DIRECTION NOT WORKING

    if data.clockwise == True:
        angle -= 6
        img_copy = pygame.transform.rotate(circle_arrow_cl, angle)
        win.blit(pygame.transform.rotate(circle_arrow_cl, angle), (WIDTH//2 - img_copy.get_width()//2, HEIGHT//2 - img_copy.get_height()//2))
    elif data.clockwise == False:
        angle += 6
        img_copy2 = pygame.transform.rotate(circle_arrow_anticl, angle)
        win.blit(pygame.transform.rotate(circle_arrow_anticl, angle), (WIDTH//2 - img_copy2.get_width()//2, HEIGHT//2 - img_copy2.get_height()//2))
    
    if data.player.actions[3] == True:
        draw_yes.draw(win)
        draw_no.draw(win)


def drawPlayer():
    """takes data as input and renders player cards on pygame win"""
    global data, send_data, cur_page_index, cards_pos, win
    num_cards_page = 7

    while cur_page_index - 1 > len(data.player.hand)/num_cards_page:
        cur_page_index -= 1

    temp = list(data.player.hand)
    hand_pages = [[]]
    while temp:
        if len(hand_pages[-1]) == num_cards_page:
            hand_pages.append([])
        hand_pages[-1].append(temp.pop(0))

    i = 0
    while True:
        try: 
            left_start = hand_left_edge + ((hand_width - ((len(hand_pages[cur_page_index]) * (card_width + card_space)) - card_space)) // 2)
            break
        except:
            cur_page_index -= 1

    for card in hand_pages[cur_page_index]:
        lift = 0
        if data.game_stage == 'fix_hand':
            if data.player.hand.index(card) == send_data[0]: lift = card_height//5
        elif data.game_stage == 'main_game' and data.player.actions[1] != False:
            #will only trigger if server sends indeces of playable cards
            if data.player.hand.index(card) in send_data[0]: lift = card_height//5

        coord_x = left_start + (i * (card_width + card_space))
        if cards_pos[card.suit, card.val][1] == False:
            cards_pos[card.suit, card.val][0] = (coord_x, hand_height - lift)
        win.blit(card.surface, card.rect.topleft)
        i += 1
    for card in data.player.hand:
        if card not in hand_pages[cur_page_index]: 
            cards_pos[card.suit, card.val][0] = (2*WIDTH, 2*HEIGHT)

    if len(data.player.hand) > num_cards_page and cur_page_index != 0:
        left_arrow_rect.right = left_start - card_width//2
        left_arrow_rect.centery = hand_height + card_height//2
        win.blit(left_arrow, left_arrow_rect.topleft)
    else: left_arrow_rect.centerx = 2 * WIDTH

    
    if len(data.player.hand) > num_cards_page and cur_page_index != hand_pages.index(hand_pages[-1]):
        right_arrow_rect.left = left_start + (i * (card_width + card_space) - card_space) + card_width//2
        right_arrow_rect.centery = hand_height + card_height//2
        win.blit(right_arrow, right_arrow_rect.topleft)
    else: right_arrow_rect.centerx = 2 * WIDTH

    for i in range(3):
        coord_x = MARGIN + (i * (card_width + card_space))
        if data.player.is_bottom_cards[i] == True:
            bottom_card = HiddenCards(1)
            data.player.bottom_cards[i] = bottom_card
            bottom_card.rect.topleft = (coord_x, hand_height)
            win.blit(bottom_card.surface, bottom_card.rect.topleft)

        lift = 0
        if data.game_stage == 'fix_hand':   
            if i == send_data[1]: lift = card_height//5
        k = len(data.player.top_cards[i]) - 1
        for card in data.player.top_cards[i]:
            cards_pos[card.suit, card.val][0] = (coord_x, (hand_height - (k * (card_height // 5)) - lift))
            win.blit(card.surface, card.rect.topleft)
            k -= 1


def drawOpps():
    """takes data as input and renders all opponents' cards on pygame win"""
    #blit pos is different from rect pos
    global data, win

    opp_width = (3 * card_width) + (2 * card_space)
    opp_space = ((WIDTH - 2*MARGIN) - ( len(data.opp_list) * opp_width ) ) // (len(data.opp_list) + 1)
    opp_fixed_height = MARGIN + card_height//2
    hidden_card = HiddenCards(1)

    index = 0
    for opp in data.opp_list:
        opp_lstart = (MARGIN + opp_space) + (index * ( opp_width + opp_space ))

        
        if data.turn == index:
            opp.highlightRect(opp_lstart, opp_space, opp_width)
            pygame.draw.rect(win, AMBER, opp.highlight)

        if opp.eat == True:
            opp.highlightRect(opp_lstart, opp_space, opp_width)
            pygame.draw.rect(win, 'red', opp.highlight)

        for i in range(3):
            coord_x = opp_lstart + (i * (card_width + card_space))
            if opp.bottom_cards[i] == True:
                win.blit(hidden_card.surface, (coord_x, opp_fixed_height))
            k = 0
            for card in opp.top_cards[i]:
                card.update() # very inefficient. this runs every frame
                win.blit(card.surface, (coord_x, (opp_fixed_height + (k * (card_height // 5)))))
                k += 1
        
        opp_name = font.render(opp.name, True, "white")
        win.blit(opp_name, (opp_lstart, MARGIN))
        opp_handinfo = font.render(f"HAND: {opp.len_hand}", True, "white")
        opp_hand_rect = opp_handinfo.get_rect()
        opp_hand_rect.right = opp_lstart + opp_width
        win.blit(opp_handinfo, (opp_hand_rect.left, MARGIN))

        index += 1


def drawDetailCards():
    """takes data and renders last_cards to the left of the screen"""
    global data, win
    i = 0
    for card in data.detail_cards:
        card.update()
        card_copy = card.surface.copy()
        win.blit(card_copy, (WIDTH//4 + (i * card_width), playDeck_topleft[1]))
        i += 1


def renderGame():
    """takes data and renders basics of the game to pygame win"""
    global data, send_data, win
    drawGameDecks()
    drawPlayer()
    drawOpps()
    drawDetailCards()


def play(event):
    """interprets what action player has to play from data"""
    global send_data, data
    actions = data.player.actions
    if actions[0] == False:
        i = 0
        for action in actions:
            if action:
                if i == 1:
                    playHand(event.pos, event.button)
                elif i == 2:
                    playTop(event.pos, event.button)
                elif i == 3:
                    playDraw(event)
                elif i == 4:
                    pass
                elif i == 5:
                    playBottom(event.pos, event.button)
            i += 1


def playHand(m_pos, button):
    """plays handcards"""
    global data, send_data
    playable_index = data.player.actions[1]
    i = 0
    for card in data.player.hand:
        if card.rect.collidepoint(m_pos) == True and button == 3 and i in playable_index:
            if not send_data[0]:
                send_data[0].append(i)
            elif send_data[0]:
                if card.val == data.player.hand[send_data[0][0]].val:
                    if i in send_data[0]:
                        send_data[0].remove(i)
                    elif i not in send_data[0]:
                        send_data[0].append(i)
        if card.rect.collidepoint(m_pos) == True and button == 1 and i in playable_index:
            if send_data[0]:
                if i in send_data[0]:
                    send_data[1] = True
                    pass
                elif i not in send_data[0]:
                    if card.val == data.player.hand[send_data[0][0]].val:
                        send_data[0].append(i)
                        send_data[1] = True
            elif not send_data[0]:
                send_data[0].append(i)
                send_data[1] = True
        i += 1


def playTop(m_pos, button):
    """takes data as input and returns index of card(s) played"""
    global data, send_data
    playable_index = data.player.actions[2]  
    i = 0
    for cards in data.player.top_cards:
        for card in cards:
            if card.rect.collidepoint(m_pos) == True and button == 1 and i in playable_index:
                send_data[0] = [i]
                send_data[1] = True
        i += 1


def playBottom(m_pos, button):
    """edits send_data with player actions for bottom_cards"""
    global send_data, data
    i = 0
    for card in data.player.bottom_cards:
        if card.rect.collidepoint(m_pos) == True and button == 1:
            send_data[0] = [i]
            send_data(send_data)
        i += 1


def playDraw(event):
    """checks if user wants to draw or not based on input"""
    global send_data
    draw_yes.check_input(event)
    draw_no.check_input(event)
    if draw_yes.active == True:
        send_data = ['y', True]
        draw_yes.active = False
    elif draw_no.active == True:
        send_data = ['n', True]
        draw_no.active = False


def checkArrow(m_pos, button):
    """checks if arrow button has been pressed. Adjusts relevant parameters accordingly"""
    global cur_page_index, left_arrow_rect, right_arrow_rect
    if left_arrow_rect.collidepoint(m_pos) and button == 1: cur_page_index -= 1
    if right_arrow_rect.collidepoint(m_pos) and button == 1: cur_page_index += 1


def fixHand(event):
    """uses user input to globally edit send_data. Then used to send to server. returns None"""
    global offset_x, offset_y, send_data, data, cards_pos

    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
        """switches cards"""
        for hand_card in data.player.hand:
            if hand_card.rect.collidepoint(event.pos):
                send_data[2] = 's'
                if send_data[0] != data.player.hand.index(hand_card):
                    send_data[0] = data.player.hand.index(hand_card)
                else: send_data[0] = None

        for top_cards in data.player.top_cards:
            for top_card in top_cards:
                if top_card.rect.collidepoint(event.pos):
                    send_data[2] = 's'
                    if send_data[1] != data.player.top_cards.index(top_cards):
                        send_data[1] = data.player.top_cards.index(top_cards)
                    else: send_data[1] = None

    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        #doubles cards
        for card in data.player.hand:
            if card.rect.collidepoint(event.pos):
                cards_pos[card.suit, card.val][1] = True
                m_x, m_y = event.pos
                offset_x = card.rect.x - m_x
                offset_y = card.rect.y - m_y

    elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        for hand_card in data.player.hand:
            for top_cards in data.player.top_cards:
                for top_card in top_cards:
                    if top_card.rect.collidepoint(event.pos) and top_card.val == hand_card.val and hand_card.rect.collidepoint(event.pos):
                        send_data[0], send_data[1], send_data[2] = data.player.hand.index(hand_card), data.player.top_cards.index(top_cards), 'd'
                    else:
                        cards_pos[hand_card.suit, hand_card.val][1] = False
                    offset_x, offset_y = None, None
                     
    elif event.type == pygame.MOUSEMOTION:
        for card in data.player.hand:
            if cards_pos[card.suit, card.val][1] == True:
                m_x, m_y = event.pos
                cards_pos[card.suit, card.val][0] = (m_x + offset_x, m_y + offset_y)


def handle_clientsocket():
    """communicates with server using data and send_data"""
    global data, send_data, title_screen

    clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    while title_screen == True:
        if title_continue.active == True:
            """player has pressed continue to connect"""
            
            try:
                clientsocket.connect(ADDR)
                clientsocket.settimeout(5.0)
                title_screen = False
                break
            except socket.error as e:
                print(e)
        
    while True:
        try:
            temp_data = pickle.loads(clientsocket.recv(4096))
            try: cardsUpdate(temp_data)
            except: pass
            data = temp_data
        except: pass

        if data == "____NODATA":
            pass

        elif data.game_stage == 'connect':
            clientsocket.sendall(pickle.dumps(get_name.text))
            send_data = [None, None, None, False]

        elif data.game_stage == 'wait_for_opps':
            pass

        elif data.game_stage == 'fix_hand':
            """dealcards and allow players to fix hand"""
            if len(send_data) == 4:
                if send_data[0] != None and send_data[1] != None and send_data[2] != None:
                    clientsocket.sendall(pickle.dumps(send_data))

                    if send_data[3] == False:
                        #player has not ended fixhand turn
                        send_data = [None, None, None, False]

                elif send_data[3] == True:
                    clientsocket.sendall(pickle.dumps(send_data))
                    """send_data has list of indeces/ 'y' or 'n' as index 0. If index 1 is true, send send_data"""
                    send_data = [[], False]
                    clientsocket.sendall(pickle.dumps(send_data))
                else:
                    time.sleep(DATA_TIME)
                    clientsocket.sendall(pickle.dumps("no_move"))


        elif data.game_stage == 'main_game':
            """main game is here"""
            if send_data[1] == True and send_data[0]:
                clientsocket.sendall(pickle.dumps(send_data))
                send_data = [[], False]
            else:
                clientsocket.sendall(pickle.dumps('____NODATA'))


def drawGUI():
    """draws and processes input from GUI"""
    run = True

    while run:
        global title_screen 
        global data, send_data

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                run = False
                pygame.quit()
                sys.exit()

            if title_screen == True:
                for box in title_boxes:
                    box.check_input(event)
                title_continue.check_input(event)

            elif title_screen == False:

                if data == '____NODATA': 
                    pass
                
                elif data.game_stage == 'wait_for_opps':
                    pass

                elif data.game_stage == 'fix_hand':
                    if len(send_data) == 4:
                        fixHand(event)
                        fixhand_done.check_input(event)
                        if fixhand_done.active:
                            send_data[3] = True
                            fixhand_done.active = False

                elif data.game_stage == 'main_game':
                    if event.type == pygame.MOUSEBUTTONDOWN:

                        play(event)
                        checkArrow(event.pos, event.button)

                        if data.player.actions[3]:
                            playDraw(event)

        if title_screen == True:
            """renders title screen"""
            win.fill('black')    
            for box in title_boxes:
                box.update()
                box.draw(win)
            title_continue.draw(win)
                
        elif title_screen == False and data == "____NODATA":
            pass

        elif data.game_stage == 'connect':
            pass

        elif data.game_stage == 'wait_for_opps':
            win.fill('blue')
            connect_text = font.render("CONNECTING...", True, "white")
            win.blit(connect_text, (WIDTH//2, HEIGHT//2))

        elif data.game_stage == 'fix_hand':
            """dealcards and allow players to fix hand. Lowest card player also plays here"""
            win.fill(POKER_GREEN)
            drawPlayer()
            drawOpps()
            fixhand_done.draw(win)

        elif data.game_stage == 'main_game':
            """main game is here"""
            if data.player.eat: win.fill('red')
            elif data.turn == 'own': win.fill(AMBER)
            else: win.fill(POKER_GREEN)
            renderGame()

        pygame.display.update()
        #event.clear() -- quits window - safeguard for "window not responding"
        clock.tick(FPS)


def main():
    server_comm = threading.Thread(target=handle_clientsocket)
    server_comm.start()
    drawGUI()


if __name__ == "__main__":
    main()
