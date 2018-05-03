import socket
import asyncio
import json

class tracker(object):
    port = 12001
    def __init__(self):
        self.peer_sockets = {}
        self.server_sock = socket.sockets(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.bind((socket.gethostname(), tracker.port))
        self.server_sock.listen(256)

    async def listen_new(self):
        (client_sock, client_addr) = self.server_sock.accept()
        init = client_sock.recv(1)
        if init == b'\xAA':
            self.peer_sockets[client_addr] = client_sock
            await client_sock.send(b"\x55", 1)
        coro1 = self.new_peer(client_addr)
        coro2 = self.send_peer_list(client_addr)
        asyncio.ensure_future(coro1)
        asyncio.ensure_future(coro2)

    async def send_peer_list(self, client_addr):
        peer_list = list(self.peer_sockets.keys())
        peer_list.remove(client_addr)
        to_send_peer = {"type": "peer list", "peers": peer_list}
        to_send_peer = json.dumps(to_send_peer)

        self.peer_sockets[client_addr].send(to_send_peer)



    async def new_peer(self, client_addr):
        to_send = {"type": "join", "address": self.peer_sockets[client_addr]}
        to_send = json.dumps(to_send)

        for cl_a in self.peer_sockets:
            if cl_a != client_addr:
                try:
                    self.peer_sockets[cl_a].send(to_send)
                except:
                    pass





