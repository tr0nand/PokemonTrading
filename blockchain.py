import hashlib
import json
from time import time
from uuid import uuid4
import pandas as pd
import random
import pokemon




#Blockchain class

class Blockchain(object):
    def __init__(self):
        #Existing Blockchain
        self.chain=[]
        #Current trades pending
        self.current_trade = []
        self.nodes = set()
        #Create genesis block
        self.new_block(proof=0,previous_hash='0')

    def nodereg(self,node):
        self.nodes.add(node)

    def new_block(self,proof,previous_hash = None):
        #Create a new block after mining in the blockchain
        #previous_hash = None for the genesis block
        block = {
        'index':len(self.chain) + 1,
        'timestamp': time(),
        'trade': self.current_trade,
        'proof': proof,
        'previous_hash': previous_hash or self.hash(self.chain[-1]),
        }
        self.current_trade=[]
        self.chain.append(block)
        return block



    def new_transaction(self,trainer1,trainer2,sentby1,sentby2):
        #creates a new trade to go into next mined block
        self.current_trade.append(
        {
            'trainer1': trainer1,
            'trainer2': trainer2,
            'sentby1': sentby1,
            'sentby2' : sentby2,
        }
        )
        return self.last_block['index'] + 1

    def proof_of_work(self,last_proof):
        #Simple proof of work algorithm:

        proof = 0;
        while self.valid_proof(last_proof,proof) is False:
            proof +=1

        return proof

    def valid_proof(self,last_proof,proof):
        guess = str(last_proof+proof).encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == '0000'



    @staticmethod
    def hash(block):
        #Creates a SHA-256 hash of a block

        block_string = json.dumps(block,sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()


    @property
    def last_block(self):
        # Returns the last Block in the chain
        return self.chain[-1]
