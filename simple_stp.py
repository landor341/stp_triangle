import argparse
import socket
from threading import Thread
import time
import os

# A dictionary container to different values for the first header byte
HeaderCodes = {
    "WEIGHT": 0b00,
    "BROADCAST": 0b01,
    "MESSAGE": 0b10,
    "SHUTDOWN": 0b11
}


class Node:
    def __init__(self, port: int, node_id: int, weight: int):
        self.node_id = node_id
        self.base_port = port - node_id  # The base port. All nodes have port of base_port + id
        self.thread_signals = {  # Used to share data between threads. Prevent weird state errors
            "weight": None,
            "cur_user_input": ""
        }

        # Records weight of 3 Nodes, including self
        self.neighbors = [None, None, None]  # Maps Node id to it's known weight
        self.neighbors[node_id-1] = self.__calculate_weight(weight, node_id)
        self.dest = None  # The dest id when this Node is active. Is none when not active
        self.running = False  # Used in run_simple_stp method to indicate the Node has not shut down yet

        self.send_time = 0  # The last time a handshake was sent when active
        self.recv_time = time.time()  # The last time a handshake was received when active

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        self.sock.settimeout(0.05)  # Add a small delay. We do not want it to block forever
    
    def run_simple_stp(self) -> None:
        # Set self.running until the user tells the program to exit
        self.running = True

        # Start the initial election
        self.start_election()
        # Start the CLI input handler
        self.__start_cli_thread()
        while self.running:
            # If a change_weight command was received then update weight and restart election
            if self.thread_signals["weight"] is not None:
                self.neighbors[self.node_id-1] = self.thread_signals["weight"]
                self.thread_signals["weight"] = None
                self.start_election()

            # See if a new message is ready to be handled
            try:
                data, (ip, port) = self.sock.recvfrom(3)
                self.handle_message(port - self.base_port, data)
            except (socket.timeout, ConnectionResetError):
                pass  # No data to receive, do nothing

            # If this node is active and has another active node to send data to
            if self.dest:
                # Send a handshake every two seconds
                if time.time() - self.send_time > 2 and self.dest:
                    message = HeaderCodes["MESSAGE"].to_bytes(1, byteorder="big") + (0).to_bytes(2, byteorder="big")
                    self.sock.sendto(message, ('127.0.0.1', self.dest + self.base_port))
                    self.send_time = time.time()
                # If the other active node is unresponsive for 10 seconds then restart election
                if self.dest and time.time() - self.recv_time > 10:
                    self.start_election()
            self.__print_prompt()

        # Send shutdown message on shutdown
        message = HeaderCodes["SHUTDOWN"].to_bytes(1, byteorder="big") + (0).to_bytes(2, byteorder="big")
        for i in range(2):
            self.sock.sendto(message, ('127.0.0.1', self.base_port + 1 + (self.node_id + i) % 3))
        self.sock.close()

    def __print_prompt(self):
        # Print's the current state of the Node.
        # If it's active then it tells what the other active node is and the last time a handshake occurred
        # If it's disabled it says what the id's of the active nodes are
        message = "\rNode " + str(self.node_id)
        if self.dest is None:
            message += "[Quiet]"
            message += "[weight=["
            message += ('000' if self.neighbors[0] is None else str(self.neighbors[0])) + ","
            message += ('000' if self.neighbors[1] is None else str(self.neighbors[1])) + ","
            message += ('000' if self.neighbors[2] is None else str(self.neighbors[2])) + "]]"
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
        """Meant to be run in a multithreaded fashion. Handles CLI input handling"""
        # constants for the command formats
        elect_command = "reelect"
        print_command = "print"
        weight_command = "change_weight "  # Takes a number afterward

        while self.running:
            # Reset the current input
            self.thread_signals["cur_user_input"] = ""

            # Loop receiving chars to add to the cur_user_input until the user presses enter
            # Can't receive with input(), because when the other thread prints the updated status
            # it would cause the old input to be split across lines
            last_char = ""
            while self.running and (last_char != '\r'):
                if last_char == '\b':
                    self.thread_signals["cur_user_input"] = self.thread_signals["cur_user_input"][:-1]
                elif last_char.isalnum() or last_char in ' _':
                    self.thread_signals["cur_user_input"] += last_char
                last_char = read_char()

            # Handle the different messages
            message = self.thread_signals["cur_user_input"].strip()
            if message == "exit":  # Shutdown program
                self.running = False
            elif message == print_command:  # Print out current network state
                print("\r\n\r\nCurrent node weight are: ", self.neighbors, end="\r\n")
                self.__print_nodes()
            elif message == elect_command:  # Restart election
                self.thread_signals["weight"] = self.__calculate_weight(self.neighbors[self.node_id-1], self.node_id)
            elif message[:len(weight_command)] == weight_command:  # Change weight
                try:  # If weight_command isn't followed by an integer then it's formatted wrong
                    new_weight = int(message.split(weight_command)[1])
                    # Weight must be in 3 digit range to match CLI printing length
                    if new_weight < 100 or new_weight > 900:
                        raise ValueError()
                    self.thread_signals["weight"] = self.__calculate_weight(new_weight, self.node_id)
                except ValueError:
                    print("\r\n\r\nInvalid weight", end="\r\n")
            print()

    def handle_message(self, receive_id: int, data: bytes) -> None:
        """
            receive_id: The id that the data was received from
            data: A 3 byte header from another simplified STP Node
            Decides how to handle the data from another node
        """

        if receive_id > 3 or receive_id < 1:
            return  # Ignore any messages from non-valid nodes

        if data[0] == HeaderCodes["WEIGHT"] or data[0] == HeaderCodes["BROADCAST"]:
            # Was a message alerting of a weight update or a new election broadcast
            self.neighbors[receive_id-1] = self.__calculate_weight((data[1] << 8) + data[2], receive_id)
            self.calculate_topology()

            # If alerted of a new election then send back a weight update to the Node
            if data[0] == HeaderCodes["BROADCAST"]:
                response = HeaderCodes["WEIGHT"].to_bytes(1, byteorder="big")
                response += self.neighbors[self.node_id-1].to_bytes(2, byteorder="big")
                self.sock.sendto(response, ('127.0.0.1', self.base_port + receive_id))
        elif data[0] == HeaderCodes["MESSAGE"]:
            # Received a new handshake/hello message from an active node
            if receive_id == self.dest:
                self.recv_time = time.time()
            else:  # Error: one of the nodes incorrectly this the active node. Alert a new election process
                self.start_election()
        elif data[0] == HeaderCodes["SHUTDOWN"]:
            # A node is shutting down.
            self.neighbors[receive_id-1] = None
            self.calculate_topology()

    def start_election(self):
        # send new election message to both neighbors
        message = HeaderCodes["BROADCAST"].to_bytes(1, byteorder="big")
        message += self.neighbors[self.node_id-1].to_bytes(2, byteorder="big")
        for i in range(2):
            self.sock.sendto(message, ('127.0.0.1', self.base_port + 1 + (self.node_id + i) % 3))
            self.neighbors[(self.node_id + i) % 3] = None

        # Reset timers for election process.
        # We assume election finishes before the timeout period
        self.recv_time = time.time()
        self.send_time = time.time()

    def calculate_topology(self):
        """Calculates which nodes are current active"""
        # Set id and weight variables for easy reference. id1/w1 and id2/w2
        # don't correlate to id of 1/2, they are the ids/weight for the nodes
        # that are after self.node_id using modulus arithmetic
        id1 = (self.node_id % 3) + 1
        id2 = ((self.node_id + 1) % 3) + 1
        w = self.neighbors[self.node_id-1]
        w1 = self.neighbors[id1-1]
        w2 = self.neighbors[id2-1]

        # Dest is none by default, if lowest node
        self.dest = None

        # If this is an active node, set the dest to the other active node. Based on priority
        if w1 is not None:
            if w2 is None:
                self.dest = id1
            elif w2 > w1 and w > w1:
                self.dest = id2
            elif w1 > w2 and w > w2:
                self.dest = id1
        elif w2 is not None:
            self.dest = id2

        # Reset the timers after a change in topology
        self.recv_time = time.time()
        self.send_time = time.time()

    @staticmethod
    def __calculate_weight(pre_weight, node_id):
        """
            Calculate the weight for a node by replacing the lowest 2 bits
            with the id to ensure uniqueness
        """
        return ((pre_weight >> 2) << 2) + node_id

    def __print_nodes(self):
        """Super ugly method for printing out a nice visual of the nodes"""
        top_border = "___________"

        print(" " * 4, end="", sep="")
        print(top_border, end="", sep="")
        print(" " * 17, end="", sep="")
        print(top_border)

        print(" " * 3, "|", end="", sep="")
        print("  ", "Node 1", "   |", end="", sep="")
        print(" " * 15, "|", end="", sep="")
        print("  ", "Node 2", "   |", sep="")

        print(" " * 3, "|", end="", sep="")
        print(self.__get_node_state(1), sep="", end="")
        print(" " * 15, "|", end="", sep="")
        print(self.__get_node_state(2), sep="")

        print(" " * 3, "|", end="", sep="")
        if True or self.neighbors[0] is None:
            weight = ('000' if self.neighbors[0] is None else str(self.neighbors[0]))
            print("Weight: ", weight, "|", end="", sep="")
        print(" " * 15, "|", end="", sep="")
        if True or self.neighbors[1] is None:
            weight = ('000' if self.neighbors[1] is None else str(self.neighbors[1]))
            print("Weight: ", weight, "|", sep="")

        print(" " * 4, "-"*11, " " * 17, "-"*11, sep="")

        print("\r\n" * 4, sep="", end="") # TOOD: Add joining lines

        print(" " * 19, end="", sep="")
        print(top_border, sep="")
        print(" " * 18, end="", sep="")
        print("|  ", "Node 3", "   |", sep="")
        print(" " * 18, "|", end="", sep="")
        print(self.__get_node_state(3), sep="")
        print(" " * 18, "|", end="", sep="")
        if True or self.neighbors[1] is None:
            weight = ('000' if self.neighbors[2] is None else str(self.neighbors[2]))
            print("Weight: ", weight, "|", sep="")
        print(" " * 19, end="", sep="")
        print("-"*11, sep="")

    def __get_node_state(self, id):
        """Helper function used to print node states"""
        if self.neighbors[id-1] is None:
            return "    Off    |"
        else:
            if self.neighbors[(id % 3)] is not None:
                if self.neighbors[(id % 3)] > self.neighbors[id-1]:
                    if self.neighbors[(id + 1) % 3] is not None:
                        if self.neighbors[(id+1) % 3] > self.neighbors[id-1]:
                            return "  Disabled |"
            return "  Enabled  |"



def main():
    """ Gets the id, weight, and port parameters then initializes and runs a simplified STP node"""
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("id", type=int, choices=range(1,4))
    arg_parser.add_argument("weight", type=int)
    arg_parser.add_argument("port", type=int)
    args = arg_parser.parse_args()
    if args.weight < 100 or args.weight > 901:
        raise ValueError("Weight must be between 100 and 900")
    node = Node(args.port, args.id, args.weight)
    node.run_simple_stp()


'''
    Using this article: stackoverflow.com/questions/5419389/how-to-overwrite-the-previous-print-to-stdout
    I was able to find a way to read input as a single character.
    This was required to implement a system that allows me to print new values
    to the screen while also reading input
'''
if os.name == 'nt':
    import msvcrt

    def read_char():
        return msvcrt.getch().decode()
else:  # Unix based system
    import sys
    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    def read_char():
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

# If main file, run main function
if __name__ == "__main__":
    main()
