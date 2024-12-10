import argparse
import socket
from threading import Thread
import time
import os


HeaderCodes = {
    "WEIGHT": 0b00,
    "BROADCAST": 0b01,
    "MESSAGE": 0b10,
    "SHUTDOWN": 0b11
}

class Node:
    def __init__(self, port: int, node_id: int, weight: int):
        self.port = port
        self.node_id = node_id
        self.base_port = port - node_id
        self.disabled = True
        self.weight = weight
        self.thread_signals = {
            "weight": None,
            "print": False,
            "cur_user_input": ""
        }

        # Records weight of 3 Nodes, including self
        self.neighbors = [None,None,None]
        self.dest = None
        self.set_nodes = 0

        self.send_time = 0
        self.recv_time = time.time()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        self.sock.settimeout(0.05)
    
    def run_simple_stp(self) -> None:
        self.running = True
        self.start_election()
        self.__start_cli_thread()
        while self.running:
            if self.thread_signals["weight"] is not None:
                self.weight = self.thread_signals["weight"]
                self.thread_signals["weight"] = None
                self.start_election()

            try:
                data, (ip, port) = self.sock.recvfrom(3)
                self.handle_message(port - self.base_port, data)
            except socket.timeout:
                pass # No data to receive, do nothing
            if not self.disabled:
                if time.time() - self.send_time > 2 and self.dest:
                    message = HeaderCodes["MESSAGE"].to_bytes(1, byteorder="big") + (0).to_bytes(2, byteorder="big")
                    self.sock.sendto(message, ('127.0.0.1', self.dest + self.base_port))
                    self.send_time = time.time()
                if not self.disabled and time.time() - self.recv_time > 10:
                    self.start_election()
            self.__print_prompt()

    def __print_prompt(self):
        message = "\rNode " + str(self.node_id)
        if self.disabled:
            message += " [Disabled]"
            message += "[active_nodes=" + str((self.node_id % 3) + 1) + ", " + str(((self.node_id + 1) % 3) + 1) + "]"
        else:
            message += " [Dest=" + str(self.dest) + "]"
            message += "[last_hello=" + time.strftime("%H:%M:%S", time.localtime(self.recv_time)) + "]"
        message += ": " + self.thread_signals["cur_user_input"]
        print(message, sep="", end="", flush=True)


    def __start_cli_thread(self) -> None:
        """
            A method that starts a new thread to handle the Node's CLI
            for exiting, changing weight, and printing topology
        """
        Thread(target=self.__run_cli).start()

    def __run_cli(self):
        weight_command = "change_weight "
        while self.running:
            self.thread_signals["cur_user_input"] = ""
            last_char = ""
            while self.running and (last_char != '\r'):
                if last_char == '\b':
                    self.thread_signals["cur_user_input"] = self.thread_signals["cur_user_input"][:-1]
                else:
                    self.thread_signals["cur_user_input"] += last_char
                last_char = readChar()
            message = self.thread_signals["cur_user_input"].strip()

            if message == "exit":
                self.running = False
            elif message == "print":
                print()
                print("Current node weight are: ", self.neighbors)
            elif message == "reelect":
                self.thread_signals["weight"] = self.weight
            elif message[:len(weight_command)] == weight_command:
                try:
                    new_weight = int(message.split(weight_command)[1])
                    self.thread_signals["weight"] = new_weight
                except ValueError:
                    print("Invalid weight")
            print()

    def handle_message(self, receive_id: int, data: bytes) -> None:
        if receive_id > 3:
            return  # Ignore any messages not between nodes

        if data[0] == HeaderCodes["WEIGHT"] or data[0] == HeaderCodes["BROADCAST"]:
            if self.is_electing() and self.neighbors[receive_id-1] is None:
                self.set_nodes += 1
            self.neighbors[receive_id-1] = (data[1] << 8) + data[2] + receive_id
            self.calculate_topology()

            if data[0] == HeaderCodes["BROADCAST"]:
                response = HeaderCodes["WEIGHT"].to_bytes(1, byteorder="big") + self.weight.to_bytes(2, byteorder="big")
                self.sock.sendto(response, ('127.0.0.1', self.base_port + receive_id))
        elif data[0] == HeaderCodes["MESSAGE"]:
            if receive_id == self.dest:
                self.recv_time = time.time()
            else:  # Error: one of the nodes incorrectly thought I was the highest priority
                self.start_election()
        elif data[0] == HeaderCodes["SHUTDOWN"]:
            self.neighbors[receive_id-1] = None
            self.calculate_topology()

    def is_electing(self):
        return self.set_nodes < 2

    def start_election(self):
        pass
        # send broadcast message to both neighbors
        message = HeaderCodes["BROADCAST"].to_bytes(1, byteorder="big") + self.weight.to_bytes(2, byteorder="big")
        for i in range(2):
            self.sock.sendto(message, ('127.0.0.1', self.base_port + 1 + (self.node_id + i) % 3))
        self.neighbors = [None, None, None]
        self.set_nodes = 0
        self.recv_time = time.time()
        self.send_time = time.time()

    def calculate_topology(self):
        id_1 = (self.node_id % 3) + 1
        id_2 = ((self.node_id + 1) % 3) + 1
        if (
                (self.neighbors[id_1-1] is None or self.weight > self.neighbors[id_1-1])
                or (self.neighbors[id_2-1] is None or self.weight > self.neighbors[id_2-1])
        ):
            self.disabled = False
            # Calculate destination
            if self.neighbors[id_1-1] is not None:
                if self.neighbors[id_2-1] is not None:
                    self.dest = id_1 if self.neighbors[id_1-1] > self.neighbors[id_2-1] else id_2
                else:
                    self.dest = id_1
            elif self.neighbors[id_2-1] is not None:
                self.dest = id_2
        else:
            self.disabled = True
            self.dest = None

        self.recv_time = time.time()
        self.send_time = time.time()


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("id", type=int)
    arg_parser.add_argument("weight", type=int)
    arg_parser.add_argument("port", type=int)
    args = arg_parser.parse_args()
    node = Node(args.port, args.id, args.weight)
    node.run_simple_stp()


'''
    Using this article: stackoverflow.com/questions/5419389/how-to-overwrite-the-previous-print-to-stdout
    I was able to find a way to read input as a single character.
    This was required to implementing a system that allows me to print new values
    To the screen while also reading input
'''
if os.name == 'nt':
    import msvcrt

    def readChar():
        return msvcrt.getch().decode()
else:  # Unix based system
    import sys
    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    def readChar():
        ch = ""
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

if __name__ == "__main__":
    main()