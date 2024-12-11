
Running the program:
	python simple_stp.py <id> <weight> <port>
	id: A number between 1 and 3
	weight: This instance will have this weight except the bottom two bits will be replaced with the id. Weight can be between 100 and 900.
	port: Any port number. In order for instances to communicate, each instances (port - id) value must be the same
		This means that for instances with id 1,2,3 the ports will be sequential. EX. [1 to 4001, 2 to 4002, 3 to 4003] or [1 to 5123,2 to 5124, 3 to 5125]

UDP messages between nodes:
	My program implements election by having a Node send out a broadcast message with it's weight to both of the other nodes.
	If the other Node exists then they will send a weight update message back and save the electing nodes reported weight.
	A node can send out a shutdown message which will trigger the other two nodes to mark it a having a weight of None.
	The two nodes that have the highest priority will send a handshake/hello to eachother every two seconds.
	If an active Node does not receive a message for 10 seconds then it sends out a new broadcast message to restart election.


CLI Interface Description:
	I took advantage of some CLI tricks so that I can display the live state of each Node without filling the terminal with print lines.
	Before the colon contains the Nodes ID
	If the node is active then it prints out the other active nodes ID ("dest", the handshake destination) and the last time the node received a handshake message from the other active node
	If the node is not active then it prints out that it's "Quiet" (disabled, lowest priority node) and the list of the node priorities
	You can enter your commands after the colon. NOTE: It does not filter out "dirty strings". Things like backspace or pressing arrow keys will NOT work as you may expect.

CLI Interface Commands:
	"print": Prints out the current state of the three network nodes with a pretty visual (I wanted to add lines between the active nodes but didn't have time)
	"change_weight <weight>": Changes the weight of the node to the weight except the bottom two bits are replaced with the node id. Automatically restarts election if a valid weight was given, otherwise prints an error message (weight must be an int between 100 and 900)
	"exit": Exits the program
	"reelect": The current node sends out a broadcast message so it can restarts it's election process





ERROR HANDLING
The rest of this document will outline how my program handles various edge cases:

CASE: Multiple nodes start election at the same time.
	Because the election process isn't stored as a node state there are no chances of conflict. The node will always just save the most recent weights it has received from weight updates or broadcast messags.

CASE: Multiple nodes have the same the same weight
	This is only possible if multiple nodes have the same idea because the weight always has its lowest two bits replaced with the id.
	(The id is always less than 4)
	Multiple nodes having the same ID is a critical error in the program setup.

CASE: The node receives a message from a node far away
	Nodes ignore any signals that aren't from the ports described in the "Running the program" section

CASE: One node shuts down unexpectedly
	If it's an active node, then after 10 seconds the other active node will realize it shut down and send out a new election alert.
	If the shutdown node wasn't active, then nobody will notice until an update occurs to one of the other node triggering a new election message to be sent out.
	In the case of a weird state occuring, the node that incorrectly receives a handshake when it believes it is not active automatically restarts its election process.
	The worst possible case is that it takes 10 seconds for the Nodes to correct themselves, as they thought they were active but they were not.
